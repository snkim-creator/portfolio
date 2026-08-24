"""DBInsight CLI 진입점.

사용:
    python -m app.main collect [--config config/config.yaml]
    python <프로젝트경로>/app/main.py collect   # 작업 디렉터리와 무관 (스케줄러용)

명령: collect / analyze / report / run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# 스크립트로 직접 실행(python app/main.py ...)해도 app 패키지를 찾도록 프로젝트 루트를 등록.
# 스케줄러에서 작업 디렉터리가 보장되지 않는 경우를 대비한다.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.ai import reporter
from app.analyzer import findings as analyzer
from app.collector import (
    mysql_collector,
    performance_schema_collector,
    replication_collector,
    status_collector,
    transaction_collector,
)
from app.config import ConfigError, load_config
from app.logging_setup import setup_logging
from app.storage import repository, sqlite

logger = logging.getLogger("app.main")


def _load_cfg(config_path: str | None):
    """config 로드 후 로깅 설정. 실패 시 (None, exit_code)."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return None, 2
    setup_logging(cfg["logging"]["file"], cfg["logging"].get("level", "INFO"))
    return cfg, 0


def _collect_server(store, server: dict, collector_cfg: dict) -> int:
    """단일 서버에서 Snapshot 을 수집해 store 에 저장. snapshot id 반환."""
    name = server["name"]
    logger.info("[%s] Collector Start", name)
    db_conn = None
    try:
        db_conn = mysql_collector.connect(server)
        server_info = mysql_collector.get_server_info(db_conn)

        logger.info("[%s] Collecting Global Status", name)
        metrics = status_collector.collect_global_status(db_conn)

        # max_connections (변수) 도 GAUGE 로 함께 저장 → Connection Usage 계산에 사용
        max_conn = server_info.get("max_connections")
        if max_conn is not None:
            try:
                metrics.append(("max_connections", "GAUGE", float(max_conn)))
            except (TypeError, ValueError):
                pass

        logger.info("[%s] Collecting Transaction/Lock", name)
        metrics.extend(transaction_collector.collect_transaction_metrics(db_conn))
        hll = transaction_collector.collect_history_list_length(db_conn)
        if hll is not None:
            metrics.append(hll)

        logger.info("[%s] Collecting Replication", name)
        metrics.extend(replication_collector.collect_replication_metrics(db_conn))

        # 리소스 지표: InnoDB Buffer Pool 크기(설정) + DB 엔진 메모리(계측)
        bp_size = server_info.get("innodb_buffer_pool_size")
        if bp_size is not None:
            try:
                metrics.append(("innodb_buffer_pool_size", "GAUGE", float(bp_size)))
            except (TypeError, ValueError):
                pass
        db_mem = performance_schema_collector.collect_db_memory(db_conn)
        if db_mem is not None:
            metrics.append(db_mem)

        logger.info("[%s] Collecting SQL Digest", name)
        top_n = collector_cfg.get("sql_digest_top_n", 50)
        digests = performance_schema_collector.collect_sql_digests(db_conn, top_n)

        logger.info("[%s] Collecting Table I/O", name)
        table_io_top_n = collector_cfg.get("table_io_top_n", 30)
        table_io = performance_schema_collector.collect_table_io(db_conn, table_io_top_n)

        snapshot_id = repository.create_snapshot(store, server_info, server["endpoint"])
        repository.save_metrics(store, snapshot_id, metrics)
        repository.save_sql_digests(store, snapshot_id, digests)
        repository.save_table_io(store, snapshot_id, table_io)

        logger.info("[%s] Snapshot ID: %d", name, snapshot_id)
        return snapshot_id
    finally:
        if db_conn is not None:
            try:
                db_conn.close()
            except Exception:  # noqa: BLE001
                pass


def _collect_all(cfg, store) -> tuple[int, int]:
    """모든 서버를 순회 수집. (성공수, 전체수) 반환. 한 서버 실패가 다른 서버를 막지 않음."""
    servers = cfg["servers"]
    collector_cfg = cfg.get("collector", {})
    ok = 0
    for server in servers:
        try:
            _collect_server(store, server, collector_cfg)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - 서버별 격리 (PRD 섹션 28)
            logger.exception("[%s] 수집 실패: %s", server["name"], exc)
    logger.info("Collector End (%d/%d 서버 성공)", ok, len(servers))
    return ok, len(servers)


def cmd_collect(config_path: str | None) -> int:
    """설정된 모든 서버의 Snapshot 을 수집해 SQLite 에 저장한다."""
    cfg, code = _load_cfg(config_path)
    if cfg is None:
        return code

    store = None
    try:
        store = sqlite.init_db(cfg["storage"]["db_path"])
        ok, total = _collect_all(cfg, store)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Collector 실행 중 오류: %s", exc)
        return 1
    finally:
        if store is not None:
            store.close()

    print(f"수집 완료: {ok}/{total} 서버")
    return 0 if ok > 0 else 1


def cmd_analyze(config_path: str | None) -> int:
    """모든 서버의 최신 Snapshot 을 분석하여 Finding 을 생성/저장하고 요약 출력."""
    cfg, code = _load_cfg(config_path)
    if cfg is None:
        return code

    store = None
    try:
        store = sqlite.init_db(cfg["storage"]["db_path"])
        for server in cfg["servers"]:
            try:
                result = analyzer.analyze(store, cfg, server["endpoint"])
                _print_analysis(result, server["name"])
            except Exception as exc:  # noqa: BLE001 - 서버별 격리
                logger.exception("[%s] 분석 실패: %s", server["name"], exc)
        return 0
    finally:
        if store is not None:
            store.close()


def cmd_report(config_path: str | None) -> int:
    """모든 서버의 최신 Snapshot 을 분석·AI 요약하여 서버별 Markdown 리포트를 생성한다."""
    cfg, code = _load_cfg(config_path)
    if cfg is None:
        return code

    store = None
    try:
        store = sqlite.init_db(cfg["storage"]["db_path"])
        for server in cfg["servers"]:
            try:
                result = reporter.generate(store, cfg, server["endpoint"])
                _print_report(result, server["name"])
            except Exception as exc:  # noqa: BLE001 - 서버별 격리
                logger.exception("[%s] 리포트 생성 실패: %s", server["name"], exc)
        return 0
    finally:
        if store is not None:
            store.close()


def cmd_run(config_path: str | None) -> int:
    """모든 서버에 대해 collect → analyze → report 전체 파이프라인을 실행한다."""
    cfg, code = _load_cfg(config_path)
    if cfg is None:
        return code

    store = None
    try:
        store = sqlite.init_db(cfg["storage"]["db_path"])
        _collect_all(cfg, store)
        for server in cfg["servers"]:
            try:
                result = reporter.generate(store, cfg, server["endpoint"])
                _print_report(result, server["name"])
            except Exception as exc:  # noqa: BLE001 - 서버별 격리
                logger.exception("[%s] 리포트 생성 실패: %s", server["name"], exc)
        return 0
    finally:
        if store is not None:
            store.close()


def _print_report(result: dict | None, name: str) -> None:
    if not result:
        print(f"[{name}] 리포트할 Snapshot 이 없습니다. 먼저 collect 를 실행하세요.")
        return
    s = result["summary"]
    print(
        f"[{name}] 리포트: {result['report_path']}  "
        f"(CRITICAL={s.get('critical',0)} WARNING={s.get('warning',0)} INFO={s.get('info',0)})"
    )
    if not result["used_ai"]:
        print(f"[{name}] 주의: AI 실패로 fallback(규칙 기반) 리포트 생성됨. 로그 확인.")


def _print_analysis(result: dict, name: str) -> None:
    if not result.get("snapshot_id"):
        print(f"[{name}] 분석할 Snapshot 이 없습니다. 먼저 collect 를 실행하세요.")
        return
    s = result["summary"]
    print()
    print(f"# [{name}] 분석 결과 (snapshot #{result['snapshot_id']} @ {result['snapshot_time']})")
    print(f"요약: CRITICAL={s.get('critical',0)}  WARNING={s.get('warning',0)}  INFO={s.get('info',0)}")
    if result.get("counter_reset"):
        print("주의: counter 초기화(서버 재시작 등)가 감지되어 일부 rate 지표는 제외되었습니다.")
    if not result["findings"]:
        print("특이사항 없음 — 즉시 조치가 필요한 항목이 없습니다.")
        return
    for f in result["findings"]:
        print(f"[{f['severity']}] ({f['category']}) {f['metric']}: {f['message']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dbinsight", description="DBInsight CLI")
    parser.add_argument(
        "--config",
        default=None,
        help="설정 파일 경로 (기본: config/config.yaml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect", help="Snapshot 1회 수집 후 SQLite 저장")
    sub.add_parser("analyze", help="최신 Snapshot 을 분석해 Finding 생성")
    sub.add_parser("report", help="AI Daily Report(Markdown) 생성")
    sub.add_parser("run", help="collect→analyze→report 전체 실행")
    return parser


def _force_utf8_stdio() -> None:
    """Windows 콘솔 한글 깨짐 방지 + pythonw.exe(창 없는 실행) 대응.

    pythonw 로 실행하면 sys.stdout/stderr 가 None 이라 print() 가 터진다.
    → None 이면 devnull 로 대체(로그는 logs/app.log 로 남으므로 손실 없음).
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            continue
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)

    if args.command == "collect":
        return cmd_collect(args.config)
    if args.command == "analyze":
        return cmd_analyze(args.config)
    if args.command == "report":
        return cmd_report(args.config)
    if args.command == "run":
        return cmd_run(args.config)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
