"""Daily Report 생성: analyze → payload → LLM → Markdown 저장. (PRD 섹션 20~23)

AI 호출이 실패해도 Finding 은 이미 DB 에 보존되며, 이 함수는 fallback 리포트를
생성한다. (PRD 섹션 28)
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.ai import prompt
from app.ai.client import LLMClient, LLMError
from app.analyzer import digest_delta
from app.analyzer import findings as analyzer

logger = logging.getLogger(__name__)

# performance_schema timer 단위: picosecond → millisecond
_PS_TO_MS = 1e9


def generate(
    conn: sqlite3.Connection, config: Dict[str, Any], endpoint: str | None = None
) -> Optional[Dict[str, Any]]:
    """지정 서버(endpoint)의 최신 스냅샷을 분석·리포트한다.

    리포트 본문은 코드가 결정적으로 구성하고(§1.1: 상태/개수 불일치 방지),
    LLM 은 근거 데이터 위에서 'AI 코멘트' 만 작성한다(§19). AI 실패해도 리포트는 완성된다.
    """
    analysis = analyzer.analyze(conn, config, endpoint)
    if not analysis.get("snapshot_id"):
        logger.warning("리포트할 Snapshot 이 없습니다. 먼저 collect 를 실행하세요.")
        return None

    snapshot_id = analysis["snapshot_id"]
    conn.row_factory = sqlite3.Row
    current_row = conn.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    window_hours = float(config.get("report", {}).get("analysis_window_hours", 24))

    sqlctx = _sql_context(conn, current_row, window_hours)
    window = sqlctx["window"]
    top_sql = sqlctx["top_sql"]
    table_io = _table_io_changes(conn, current_row, sqlctx["baseline_id"])

    # Health 섹션용 window(24h) 카운터 delta
    wdeltas = {}
    if sqlctx["baseline_id"]:
        wdeltas = digest_delta.window_metric_deltas(
            conn, snapshot_id, sqlctx["baseline_id"],
            ["Innodb_row_lock_waits", "Innodb_row_lock_time", "Aborted_connects",
             "Aborted_clients", "Innodb_buffer_pool_wait_free", "Innodb_log_waits"],
        )

    # 결정적 본문 (사실/수치)
    body = _build_body(analysis, sqlctx, table_io, window, wdeltas)

    # AI 코멘트 (근거 데이터 기반 서술). 실패해도 리포트는 완성.
    ai_cfg = config.get("ai", {})
    used_ai = False
    ai_comment = ""
    try:
        client = LLMClient(ai_cfg)
        payload = _build_payload(analysis, top_sql, table_io, window)
        ai_comment = client.generate(
            prompt.build_system_prompt(ai_cfg.get("language", "ko")),
            prompt.build_user_prompt(payload),
        )
        used_ai = True
    except LLMError as exc:
        logger.warning("AI 코멘트 생성 실패(본문은 정상): %s", exc)

    markdown = _compose(analysis, body, ai_comment, ai_cfg, used_ai, top_sql, window)
    report_path = _write(config, analysis, markdown)
    _record(conn, analysis, report_path, ai_cfg, used_ai)

    logger.info("Report Generated: %s (ai=%s)", report_path, used_ai)
    return {"report_path": report_path, "used_ai": used_ai, "summary": analysis["summary"]}


# ── SQL 컨텍스트(기간 Delta) ────────────────────────────────────────────────
def _sql_context(conn: sqlite3.Connection, current_row, window_hours: float) -> Dict[str, Any]:
    """기간 Delta digest + window 정보 + top_sql 을 한 번에 계산."""
    endpoint = current_row["conn_endpoint"]
    baseline, partial = digest_delta.select_window_baseline(conn, endpoint, current_row, window_hours)

    if baseline is None:
        window = {
            "status": "INSUFFICIENT_DATA", "basis": "cumulative",
            "from": None, "to": current_row["snapshot_time"], "hours": None, "reset_count": 0,
        }
        return {"top_sql": _cumulative_top_sql(conn, current_row["id"]),
                "window": window, "digests": [], "baseline_id": None}

    period = digest_delta.compute_period_digests(conn, current_row["id"], baseline["id"])
    digests = period["digests"]
    window = {
        "status": "PARTIAL" if partial else "OK", "basis": "period",
        "from": baseline["snapshot_time"], "to": current_row["snapshot_time"],
        "hours": digest_delta.actual_window_hours(current_row, baseline),
        "reset_count": period["reset_count"],
    }
    rows = [d for d in digests if not digest_delta.is_admin_statement(d["digest_text"])]
    rows.sort(key=lambda d: d.get("delta_total_latency") or 0, reverse=True)

    top_sql = [
        {
            "digest_text": d["digest_text"],
            "exec": int(d["delta_execution_count"]),
            "avg_latency_ms": d["period_avg_latency_ms"],
            "rows_examined": int(d["delta_rows_examined"]),
            "rows_examined_per_exec": d["period_rows_examined_per_exec"],
        }
        for d in rows[:10]
    ]
    return {"top_sql": top_sql, "window": window, "digests": rows, "baseline_id": baseline["id"]}


def _cumulative_top_sql(conn: sqlite3.Connection, snapshot_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """이력 부족 시 fallback: 누적 총지연 기준 상위 SQL(기간 Delta 아님)."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT digest_text, execution_count, avg_latency, rows_examined "
        "FROM sql_digest_metrics WHERE snapshot_id = ? ORDER BY total_latency DESC LIMIT ?",
        (snapshot_id, limit),
    ).fetchall()
    return [
        {
            "digest_text": r["digest_text"] or "",
            "exec": r["execution_count"],
            "avg_latency_ms": round(r["avg_latency"] / _PS_TO_MS, 2) if r["avg_latency"] else None,
            "rows_examined": r["rows_examined"],
            "rows_examined_per_exec": None,
        }
        for r in rows
    ]


def _load_tio(conn: sqlite3.Connection, snapshot_id: int) -> Dict[str, tuple]:
    conn.row_factory = sqlite3.Row
    return {
        f"{r['object_schema']}.{r['object_name']}": (r["count_read"] or 0, r["count_write"] or 0)
        for r in conn.execute(
            "SELECT object_schema, object_name, count_read, count_write "
            "FROM table_io_metrics WHERE snapshot_id = ?",
            (snapshot_id,),
        )
    }


def _table_io_changes(
    conn: sqlite3.Connection, current_row, baseline_id, limit: int = 8
) -> Dict[str, Any]:
    """테이블별 read/write 를 기간 Delta 로. (개선요청 §17) baseline 없으면 누적."""
    cur = _load_tio(conn, current_row["id"])
    base = _load_tio(conn, baseline_id) if baseline_id else {}
    basis = "period" if baseline_id else "cumulative"

    rows: List[Dict[str, Any]] = []
    for tbl, (cr, cw) in cur.items():
        if base:
            br, bw = base.get(tbl, (0, 0))
            dr, dw = cr - br, cw - bw
            if dr < 0 or dw < 0:  # reset
                continue
        else:
            dr, dw = cr, cw
        if dr == 0 and dw == 0:
            continue
        rows.append({"table": tbl, "read": int(dr), "write": int(dw)})
    rows.sort(key=lambda x: x["read"] + x["write"], reverse=True)
    return {"rows": rows[:limit], "basis": basis}


def _finding_payload(f: Dict[str, Any]) -> Dict[str, Any]:
    """Finding 을 LLM payload 형태로. 근거 수치(baseline 등, P2)는 있으면 포함."""
    entry = {
        "severity": f["severity"],
        "category": f["category"],
        "metric": f["metric"],
        "current": f["current"],
        "baseline": f["baseline"],
        "message": f["message"],
    }
    for k in ("previous", "baseline_median", "baseline_p95", "change_vs_median", "threshold",
              "baseline_status", "lifecycle", "persist_days"):
        if f.get(k) is not None:
            entry[k] = f[k]
    return entry


def _build_payload(
    analysis: Dict[str, Any],
    top_sql: List[Dict[str, Any]],
    table_io: List[Dict[str, Any]],
    window: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "database": analysis.get("database"),
        "snapshot_time": analysis.get("snapshot_time"),
        "analysis_window": window,  # 분석 기간(개선요청 §3): status/from/to/hours/basis
        "summary": analysis.get("summary", {}),
        "lifecycle_summary": analysis.get("lifecycle_summary", {}),  # NEW/PERSISTENT/RESOLVED 개수
        "resolved": analysis.get("resolved", []),  # 정상화된 이전 finding
        "counter_reset": analysis.get("counter_reset", False),
        "findings": [_finding_payload(f) for f in analysis.get("findings", [])],
        # top_sql 은 분석 기간 Delta 기준(exec/avg_latency_ms/rows_examined 모두 해당 기간 값).
        # LLM payload 는 토큰 절약을 위해 digest 를 절단(전체 원문은 리포트 부록에 표시).
        "top_sql": [
            {**q, "digest_text": (q.get("digest_text") or "")[:200]} for q in top_sql
        ],
        "table_io": table_io.get("rows", []) if isinstance(table_io, dict) else table_io,
    }


def _html_escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def _truncate(text: str, n: int = 80) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:n] + ("…" if len(text) > n else "")


def _join_sections(*sections: str) -> str:
    return "\n\n".join(s.rstrip() for s in sections if s and s.strip())


def _lifecycle_section(findings: List[Dict[str, Any]], resolved: List[Dict[str, Any]]) -> str:
    """상태 변화 섹션 (개선요청 §11): NEW / PERSISTENT(연속일수) / RESOLVED."""
    new = [f for f in findings if f.get("lifecycle") == "NEW"]
    persistent = [f for f in findings if f.get("lifecycle") == "PERSISTENT"]
    if not (new or persistent or resolved):
        return ""
    lines = ["## 상태 변화 (Finding Lifecycle)", "", "### NEW"]
    lines += [f"- [{f['severity']}] ({f['category']}) {f['metric']}" for f in new] or ["- 없음"]
    lines += ["", "### PERSISTENT"]
    if persistent:
        for f in persistent:
            days = f.get("persist_days")
            suffix = f" — {days}일 연속" if days else ""
            lines.append(f"- [{f['severity']}] ({f['category']}) {f['metric']}{suffix}")
    else:
        lines.append("- 없음")
    lines += ["", "### RESOLVED"]
    lines += [f"- ({r['category']}) {r['metric']} — {r.get('message', '정상화')}" for r in resolved] or ["- 없음"]
    return "\n".join(lines)


def _regression_section(findings: List[Dict[str, Any]]) -> str:
    """SQL Regression 결정적 섹션 (개선요청 §8). before/after 수치 + 전체 쿼리 접기."""
    regs = [f for f in findings if f.get("category") == "sql_regression"]
    if not regs:
        return ""
    lines = ["## SQL Regression — 평소 대비 성능 악화", ""]
    for i, f in enumerate(regs, 1):
        lines.append(f"### {i}. 평균 실행시간 {f.get('latency_change_ratio')}배 증가")
        lines.append(f"- Baseline (7d median): {f.get('avg_latency_baseline_ms')} ms")
        lines.append(f"- 최근 기간: {f.get('avg_latency_current_ms')} ms")
        lines.append(f"- 기간 실행수: {_fmt(f.get('execution_count'))}")
        rpe_b, rpe_c = f.get("rows_examined_per_exec_baseline"), f.get("rows_examined_per_exec_current")
        if rpe_b is not None and rpe_c is not None:
            lines.append(f"- 검사행/실행: {rpe_b} → {rpe_c}")
        full = (f.get("digest_text") or "").strip()
        if full:
            lines += ["", "<details>", "<summary>쿼리 보기</summary>", "", "```sql", full, "```", "", "</details>"]
        lines.append("")
    return "\n".join(lines)


def _window_label(window: Dict[str, Any]) -> str:
    """분석 기간 한 줄 표기 (개선요청 §3)."""
    status = window.get("status")
    if status == "INSUFFICIENT_DATA":
        return "분석 기간: 비교할 이전 스냅샷 없음 (누적값 기준, 이력 부족)"
    hours = window.get("hours")
    basis = "기간 Delta" if window.get("basis") == "period" else "누적값"
    tail = " · 이력 부족으로 기간 짧음" if status == "PARTIAL" else ""
    reset = window.get("reset_count") or 0
    reset_note = f" · reset 제외 {reset}건" if reset else ""
    return f"분석 기간: {window.get('from')} ~ {window.get('to')} ({hours}h, {basis}){tail}{reset_note}"


def _sql_appendix(top_sql: List[Dict[str, Any]], window: Dict[str, Any]) -> str:
    """부하 상위 SQL 전체 쿼리를 <details> 접기 블록으로 (클릭 시 펼쳐짐)."""
    entries = [q for q in top_sql if (q.get("digest_text") or "").strip()]
    if not entries:
        return ""
    basis = "최근 기간" if window.get("basis") == "period" else "누적"
    lines = [f"## 부하 상위 SQL — 전체 쿼리 ({basis} 기준, 클릭하여 펼치기)", ""]
    for i, q in enumerate(entries, 1):
        full = q["digest_text"].strip()
        summary = _html_escape(_truncate(full, 90))
        stats = (
            f"exec={_fmt(q.get('exec'))} · "
            f"avg={q.get('avg_latency_ms')}ms · examined={_fmt(q.get('rows_examined'))}"
            f" · exam/exec={q.get('rows_examined_per_exec')}"
        )
        lines += [
            "<details>",
            f"<summary>{i}. {stats} — <code>{summary}</code></summary>",
            "",
            "```sql",
            full,
            "```",
            "",
            "</details>",
            "",
        ]
    return "\n".join(lines)


def _compose(analysis, body, ai_comment, ai_cfg, used_ai, top_sql, window) -> str:
    """결정적 본문 + AI 코멘트 + 전체 쿼리 부록 + footer."""
    parts = [body.rstrip()]
    if used_ai and ai_comment and ai_comment.strip():
        parts.append("## AI 코멘트\n\n" + ai_comment.rstrip())
    appendix = _sql_appendix(top_sql, window)
    if appendix:
        parts.append(appendix.rstrip())
    src = f"{ai_cfg.get('provider')}/{ai_cfg.get('model')}" if used_ai else "AI 코멘트 생략(호출 실패)"
    footer = f"\n\n---\n_생성: DBInsight · {src} · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n"
    return "\n\n".join(parts) + footer


# ── 결정적 리포트 본문 (개선요청 §20 구조) ──────────────────────────────────
_STATUS = [("critical", "CRITICAL", "위험"), ("warning", "WARNING", "주의"), ("info", "INFO", "정보")]

_ACTION_CHECKS = {
    "sql_regression": ["EXPLAIN 으로 실행계획 확인", "인덱스 사용/변경 여부", "최근 데이터량·분포 변화"],
    "sql": ["EXPLAIN 실행계획 확인", "인덱스 미사용 구간 점검", "불필요한 조인/스캔 검토"],
    "connection": ["커넥션 급증 원인(앱/배치) 확인", "커넥션 풀·max_connections 설정", "비정상 종료(Aborted) 확인"],
    "transaction": ["장기 트랜잭션 내용·보유 lock 확인", "애플리케이션 트랜잭션 범위", "commit 지연 여부"],
    "lock": ["경합 트랜잭션·대기 체인 확인", "핫 로우/인덱스 검토"],
    "innodb": ["buffer pool 크기·flush 설정", "물리 읽기 증가 원인", "체크포인트 부하"],
    "query": ["tmp_table_size/max_heap_table_size 검토", "정렬·그룹핑 쿼리 인덱스"],
}


def _overall_status(summary: Dict[str, Any]):
    for key, en, ko in _STATUS:
        if summary.get(key, 0) > 0:
            return en, ko
    return "NORMAL", "정상"


def _bl(analysis, key):
    b = (analysis.get("baselines") or {}).get(key)
    if b and b.get("status") == "OK":
        return b.get("median"), b.get("p95")
    return None, None


def _val(analysis, name):
    v = (analysis.get("values") or {}).get(name)
    return v


def _build_body(analysis, sqlctx, table_io, window, wdeltas) -> str:
    status_en, status_ko = _overall_status(analysis["summary"])
    return _join_sections(
        _overview_section(analysis, window, status_en, status_ko),
        _major_changes_section(analysis),
        _action_items_section(analysis),
        _findings_section(analysis),
        _lifecycle_section(analysis.get("findings", []), analysis.get("resolved", [])),
        _regression_section(analysis.get("findings", [])),
        _sql_rankings_section(sqlctx["digests"], window),
        _connection_health_section(analysis),
        _txn_lock_health_section(analysis, wdeltas),
        _innodb_health_section(analysis, wdeltas),
        _server_load_section(analysis),
        _replication_health_section(analysis),
        _table_io_section(table_io, window),
    )


def _overview_section(analysis, window, status_en, status_ko) -> str:
    s = analysis.get("summary", {})
    ls = analysis.get("lifecycle_summary", {})
    return "\n".join([
        f"# DBInsight Daily Report — {analysis.get('database')}",
        "",
        f"- DB Version: {analysis.get('db_version')}",
        f"- {_window_label(window)}",
        "",
        f"## Overall Status: {status_en} ({status_ko})",
        f"- CRITICAL {s.get('critical',0)} · WARNING {s.get('warning',0)} · INFO {s.get('info',0)}",
        f"- 상태 변화: NEW {ls.get('new',0)} · PERSISTENT {ls.get('persistent',0)} · RESOLVED {ls.get('resolved',0)}",
    ])


def _major_changes_section(analysis) -> str:
    findings = analysis.get("findings", [])
    resolved = analysis.get("resolved", [])
    items: List[str] = []
    # 1) SQL Regression 우선
    for f in findings:
        if f.get("category") == "sql_regression":
            items.append(
                f"SQL 평균 실행시간 {f.get('latency_change_ratio')}배 증가 "
                f"({f.get('avg_latency_baseline_ms')}ms → {f.get('avg_latency_current_ms')}ms)"
            )
    # 2) NEW finding (regression 제외), baseline 대비 변화 우선
    for f in findings:
        if f.get("lifecycle") == "NEW" and f.get("category") != "sql_regression":
            note = ""
            if f.get("change_vs_median") is not None:
                note = f" (7d median 대비 {f['change_vs_median']}배)"
            items.append(f"{f['metric']} 신규 발생: 현재 {f.get('current')}{note}")
    # 3) 정상화
    for r in resolved:
        items.append(f"{r['metric']} 정상화 (이전 {r.get('previous_severity')})")

    lines = ["## 오늘의 주요 변화", ""]
    if not items:
        lines.append("최근 분석 기간 동안 기준선 대비 유의미한 변화가 확인되지 않았습니다.")
    else:
        lines += [f"{i}. {t}" for i, t in enumerate(items[:6], 1)]
    return "\n".join(lines)


def _action_items_section(analysis) -> str:
    findings = analysis.get("findings", [])

    def _score(f):
        if f["severity"] == "CRITICAL":
            return 0
        if f.get("category") == "sql_regression":
            return 1
        if f["severity"] == "WARNING":
            return 2
        return 3

    ranked = sorted([f for f in findings if f["severity"] in ("CRITICAL", "WARNING")], key=_score)
    lines = ["## 오늘 DBA 확인 권장", ""]
    if not ranked:
        lines.append("즉시 확인이 필요한 항목이 없습니다.")
        return "\n".join(lines)
    for i, f in enumerate(ranked[:5], 1):
        checks = _ACTION_CHECKS.get(f.get("category"), ["관련 지표 추이 확인"])
        lines.append(f"### Priority {i} — [{f['severity']}] {f['category']}/{f['metric']}")
        lines.append(f"- 관찰: {f['message']}")
        lines.append("- 확인 권장: " + " · ".join(checks))
        lines.append("")
    return "\n".join(lines).rstrip()


def _findings_section(analysis) -> str:
    findings = analysis.get("findings", [])
    lines = ["## 확인이 필요한 항목", ""]
    if not findings:
        lines.append("특이사항 없음 — 즉시 조치가 필요한 항목이 없습니다.")
        return "\n".join(lines)
    for f in findings:
        life = f.get("lifecycle")
        days = f.get("persist_days")
        tag = f" [{life}{f' {days}일' if life == 'PERSISTENT' and days else ''}]" if life else ""
        lines.append(f"- **[{f['severity']}]** ({f['category']}) {f['metric']}{tag} — {f['message']}")
        extras = []
        if f.get("baseline_median") is not None:
            extras.append(f"7d median {f['baseline_median']}")
        if f.get("baseline_p95") is not None:
            extras.append(f"p95 {f['baseline_p95']}")
        if f.get("change_vs_median") is not None:
            extras.append(f"vs median {f['change_vs_median']}배")
        if f.get("baseline_status") == "INSUFFICIENT_DATA":
            extras.append("기준선 데이터 부족")
        if extras:
            lines.append(f"  - 근거: {' · '.join(extras)}")
    return "\n".join(lines)


def _rank(digests, keyfn, fmtfn, n=5, filt=None) -> List[str]:
    rows = [d for d in digests if (filt is None or filt(d))]
    rows.sort(key=keyfn, reverse=True)
    out = [f"- {fmtfn(d)} — `{_truncate(d['digest_text'], 60)}`" for d in rows[:n]]
    return out or ["- (해당 없음)"]


def _sql_rankings_section(digests, window) -> str:
    if window.get("basis") != "period" or not digests:
        return ""
    sec = ["## SQL Analysis (최근 기간 기준)", ""]
    sec += ["### Total DB Time Top"]
    sec += _rank(digests, lambda d: d.get("delta_total_latency") or 0,
                 lambda d: f"{(d['delta_total_latency']/1e9):,.0f}ms")
    sec += ["", "### Execution Count Top"]
    sec += _rank(digests, lambda d: d.get("delta_execution_count") or 0,
                 lambda d: f"{int(d['delta_execution_count']):,}회")
    sec += ["", "### Average Latency Top (실행 10회 이상)"]
    sec += _rank(digests, lambda d: d.get("period_avg_latency_ms") or 0,
                 lambda d: f"{d['period_avg_latency_ms']}ms (exec {int(d['delta_execution_count']):,})",
                 filt=lambda d: (d.get("delta_execution_count") or 0) >= 10)
    sec += ["", "### Rows Examined Top"]
    sec += _rank(digests, lambda d: d.get("delta_rows_examined") or 0,
                 lambda d: f"{int(d['delta_rows_examined']):,}행 (per-exec {d.get('period_rows_examined_per_exec')})")
    sec += ["", "### Full Scan Top"]
    sec += _rank(digests, lambda d: (d.get("delta_select_scan") or 0) + (d.get("delta_select_full_join") or 0),
                 lambda d: f"scan {int(d.get('delta_select_scan') or 0):,}, full_join {int(d.get('delta_select_full_join') or 0):,}",
                 filt=lambda d: (d.get("delta_select_scan") or 0) + (d.get("delta_select_full_join") or 0) > 0)
    sec += ["", "### Disk Temporary Table Top"]
    sec += _rank(digests, lambda d: d.get("delta_tmp_disk_tables") or 0,
                 lambda d: f"{int(d['delta_tmp_disk_tables']):,}개",
                 filt=lambda d: (d.get("delta_tmp_disk_tables") or 0) > 0)
    return "\n".join(sec)


def _mp(v, pct=False):
    if v is None:
        return "N/A"
    return f"{v*100:.1f}%" if pct else (f"{v:.1f}" if isinstance(v, float) else str(v))


def _connection_health_section(analysis) -> str:
    tc, tr = _val(analysis, "Threads_connected"), _val(analysis, "Threads_running")
    mc = _val(analysis, "max_connections")
    usage = (analysis.get("derived") or {}).get("connection_usage")
    tc_m, tc_p = _bl(analysis, "Threads_connected")
    tr_m, tr_p = _bl(analysis, "Threads_running")
    u_m, _ = _bl(analysis, "connection_usage")
    lines = ["## Connection Health", ""]
    lines.append(f"- Threads_connected: 현재 {_mp(tc)} · 7d median {_mp(tc_m)} · p95 {_mp(tc_p)}")
    lines.append(f"- Threads_running: 현재 {_mp(tr)} · 7d median {_mp(tr_m)} · p95 {_mp(tr_p)}")
    lines.append(f"- Connection Usage: {_mp(usage, pct=True)} (7d median {_mp(u_m, pct=True)}) · max_connections {_mp(mc)}")
    lines.append(f"- Max_used_connections: {_mp(_val(analysis, 'Max_used_connections'))}")
    return "\n".join(lines)


def _txn_lock_health_section(analysis, wdeltas) -> str:
    lines = ["## Transaction / Lock Health", ""]
    lines.append(f"- 실행 중 트랜잭션: {_mp(_val(analysis, 'innodb_trx_count'))} "
                 f"(running {_mp(_val(analysis, 'innodb_trx_running'))})")
    lines.append(f"- 최장 트랜잭션 실행시간: {_mp(_val(analysis, 'innodb_trx_longest_seconds'))} 초")
    lines.append(f"- 락 대기 트랜잭션: {_mp(_val(analysis, 'innodb_trx_lock_waiting'))}")
    lines.append(f"- 현재 row lock 대기: {_mp(_val(analysis, 'Innodb_row_lock_current_waits'))}")
    lw = (wdeltas or {}).get("Innodb_row_lock_waits")
    lt = (wdeltas or {}).get("Innodb_row_lock_time")
    if lw is not None:
        lines.append(f"- 기간 내 row lock wait 발생: {int(lw):,}건 (lock time {int(lt):,}ms)"
                     if lt is not None else f"- 기간 내 row lock wait 발생: {int(lw):,}건")
    return "\n".join(lines)


def _innodb_health_section(analysis, wdeltas) -> str:
    d = analysis.get("derived") or {}
    hit = d.get("buffer_pool_hit_ratio")
    dirty = d.get("dirty_page_ratio")
    dirty_m, _ = _bl(analysis, "dirty_page_ratio")
    total = _val(analysis, "Innodb_buffer_pool_pages_total")
    free = _val(analysis, "Innodb_buffer_pool_pages_free")
    usage = (1 - free / total) if (total and free is not None) else None
    lines = ["## InnoDB Health", ""]
    lines.append(f"- Buffer Pool Hit Ratio: {_mp(hit, pct=True)}")
    lines.append(f"- Buffer Pool 사용률: {_mp(usage, pct=True)}")
    lines.append(f"- Dirty Page Ratio: {_mp(dirty, pct=True)} (7d median {_mp(dirty_m, pct=True)})")
    hll = _val(analysis, "innodb_history_list_length")
    if hll is not None:
        hm, hp = _bl(analysis, "innodb_history_list_length")
        hm_s = f"{int(hm):,}" if hm is not None else "N/A"
        hp_s = f"{int(hp):,}" if hp is not None else "N/A"
        lines.append(f"- History List Length: {int(hll):,} (7d median {hm_s} · p95 {hp_s})")
    wf = (wdeltas or {}).get("Innodb_buffer_pool_wait_free")
    lwt = (wdeltas or {}).get("Innodb_log_waits")
    lines.append(f"- 기간 내 buffer pool wait_free: {int(wf):,}건" if wf is not None
                 else "- 기간 내 buffer pool wait_free: N/A (다음 수집부터)")
    lines.append(f"- 기간 내 log_waits: {int(lwt):,}건" if lwt is not None
                 else "- 기간 내 log_waits: N/A (다음 수집부터)")
    lines.append("> Buffer Pool Hit Ratio 가 높아도 wait_free/log_waits/lock 지표를 함께 확인한다.")
    return "\n".join(lines)


def _server_load_section(analysis) -> str:
    """수집 시점 DB 부하 + 리소스(설정/계측). 호스트 OS CPU/RAM 은 SQL 로 불가."""
    v = analysis.get("values") or {}
    rate = analysis.get("rate") or {}
    tr = v.get("Threads_running")
    trm, trp = _bl(analysis, "Threads_running")
    trm_s = f"{trm:.0f}" if trm is not None else "N/A"
    trp_s = f"{trp:.0f}" if trp is not None else "N/A"
    lines = ["## Server Load & Resource (수집 시점)", ""]
    lines.append(f"- 활성 부하 Threads_running: {_mp(tr)} (7d median {trm_s} · p95 {trp_s})")
    qps = rate.get("Queries")
    if qps is not None:
        lines.append(f"- QPS (최근 구간 평균): {qps:.0f}/s")
    trx = v.get("innodb_trx_count")
    if trx is not None:
        lines.append(f"- 실행 중 트랜잭션: {_mp(trx)}")
    bp = v.get("innodb_buffer_pool_size")
    if bp:
        lines.append(f"- InnoDB Buffer Pool 크기(설정): {bp / 1048576:.0f} MB")
    mem = v.get("db_memory_used_bytes")
    if mem:
        lines.append(f"- DB 엔진 메모리 사용(계측): {mem / 1048576:.0f} MB")
    lines.append(
        "> 호스트 OS 의 CPU/메모리 사용률은 DB 커넥션(SQL)으로 수집 불가 — "
        "node_exporter/Prometheus 또는 에이전트 필요(PRD Phase C)."
    )
    return "\n".join(lines)


def _replication_health_section(analysis) -> str:
    v = analysis.get("values") or {}
    is_replica = v.get("replica_is_replica") == 1
    slaves = v.get("Slaves_connected")
    if not is_replica and slaves is None:
        return ""
    lines = ["## Replication Health", ""]
    if is_replica:
        io = "정상" if v.get("replica_io_running") == 1 else "중단"
        sqlr = "정상" if v.get("replica_sql_running") == 1 else "중단"
        lines.append("- 역할: Replica")
        lines.append(f"- IO 스레드: {io} · SQL 스레드: {sqlr}")
        behind = v.get("replica_seconds_behind")
        if behind is not None:
            bm, bp = _bl(analysis, "replica_seconds_behind")
            bm_s = f"{int(bm)}s" if bm is not None else "N/A"
            bp_s = f"{int(bp)}s" if bp is not None else "N/A"
            lines.append(f"- 복제 지연: {int(behind)}s (7d median {bm_s} · p95 {bp_s})")
        else:
            lines.append("- 복제 지연: N/A (스레드 중단 시 NULL)")
        errno = v.get("replica_last_errno")
        note = " — SHOW REPLICA STATUS 로 Last_Error 확인" if errno else ""
        lines.append(f"- 마지막 에러 errno: {int(errno) if errno is not None else 'N/A'}{note}")
    if slaves is not None:
        lines.append(f"- 연결된 replica 수(마스터 측): {int(slaves)}")
    return "\n".join(lines)


def _table_io_section(table_io, window) -> str:
    rows = table_io.get("rows", []) if isinstance(table_io, dict) else []
    if not rows:
        return ""
    basis = "최근 기간" if table_io.get("basis") == "period" else "누적"
    lines = [f"## Table I/O Changes ({basis} 기준)", ""]
    for t in rows:
        lines.append(f"- `{t['table']}` — read {t['read']:,} · write {t['write']:,}")
    return "\n".join(lines)


def _server_slug(analysis: Dict[str, Any]) -> str:
    """리포트 파일명에 쓸 서버 식별자. 여러 서버 리포트가 서로 덮이지 않게 한다."""
    raw = analysis.get("database") or analysis.get("server_id") or "server"
    # server_id 의 :port 는 떼고, 파일명 불가 문자는 _ 로 치환
    raw = str(raw).split(":")[0]
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._-")
    return (slug or "server")[:60]


def _write(config: Dict[str, Any], analysis: Dict[str, Any], markdown: str) -> str:
    out_dir = Path(config.get("report", {}).get("output_directory", "./reports"))
    out_dir.mkdir(parents=True, exist_ok=True)
    report_date = str(analysis.get("snapshot_time", ""))[:10] or datetime.now().strftime("%Y-%m-%d")
    path = out_dir / f"{report_date}_{_server_slug(analysis)}_db_health_report.md"
    path.write_text(markdown, encoding="utf-8")
    return str(path)


def _record(
    conn: sqlite3.Connection,
    analysis: Dict[str, Any],
    report_path: str,
    ai_cfg: Dict[str, Any],
    used_ai: bool,
) -> None:
    report_date = str(analysis.get("snapshot_time", ""))[:10]
    conn.execute(
        "INSERT INTO reports (snapshot_id, report_date, report_path, ai_provider, ai_model) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            analysis["snapshot_id"],
            report_date,
            report_path,
            ai_cfg.get("provider") if used_ai else "fallback",
            ai_cfg.get("model") if used_ai else None,
        ),
    )
    conn.commit()
