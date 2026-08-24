"""Performance Schema SQL Digest 수집.

events_statements_summary_by_digest 에서 총 지연(SUM_TIMER_WAIT) 상위 N개를 가져온다.
Timer 값 단위는 picosecond(ps) 이며, 저장은 raw 값 그대로 한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

QUERIES_DIR = Path(__file__).resolve().parent.parent.parent / "queries" / "mysql"


def _load_query(name: str) -> str:
    return (QUERIES_DIR / name).read_text(encoding="utf-8")


# PRD 섹션 12.2: 4개 기준으로 Top SQL 추출. ORDER BY 컬럼은 고정 화이트리스트라 SQL 주입 안전.
_DIGEST_ORDERINGS = [
    "SUM_TIMER_WAIT",     # Total Latency
    "AVG_TIMER_WAIT",     # Average Latency
    "COUNT_STAR",         # Execution Count
    "SUM_ROWS_EXAMINED",  # Rows Examined
]


def collect_sql_digests(conn, top_n: int = 50) -> List[Dict[str, Any]]:
    """4개 기준(총지연/평균지연/실행수/검사행) 각 상위 N개를 DIGEST 로 합집합해 반환한다."""
    base_sql = _load_query("statement_digest.sql")
    union: Dict[str, Dict[str, Any]] = {}
    try:
        with conn.cursor() as cur:
            for order_col in _DIGEST_ORDERINGS:
                sql = base_sql.format(order_by=order_col)  # {order_by} 만 치환, %(limit)s 는 파라미터 유지
                cur.execute(sql, {"limit": int(top_n)})
                for r in cur.fetchall():
                    dg = r.get("DIGEST")
                    if dg:
                        union[dg] = r  # 같은 digest 는 최신 조회로 덮어씀(값 동일)
    except Exception as exc:  # noqa: BLE001 - PS 미활성/권한 부족 등 흡수
        logger.warning("SQL Digest 수집 실패 (Performance Schema 확인 필요): %s", exc)
        return list(union.values())

    rows = list(union.values())
    logger.info("Collected %d digests (4개 기준 합집합)", len(rows))
    return rows


def collect_db_memory(conn):
    """DB 엔진 메모리 사용량(계측 기반) 수집. (name, 'GAUGE', bytes) 또는 None.

    performance_schema 메모리 계측이 꺼져 있으면 0/NULL → None 반환(호스트 메모리 아님).
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT SUM(CURRENT_NUMBER_OF_BYTES_USED) AS b "
                "FROM performance_schema.memory_summary_global_by_event_name"
            )
            row = cur.fetchone()
            val = row.get("b") if row else None
            # MariaDB 는 메모리 계측이 부분적이면 합계가 음수로 나올 수 있음 → 양수만 신뢰
            if val is not None and float(val) > 0:
                return ("db_memory_used_bytes", "GAUGE", float(val))
    except Exception as exc:  # noqa: BLE001
        logger.debug("DB 메모리 계측 조회 실패: %s", exc)
    return None


def collect_table_io(conn, top_n: int = 30) -> List[Dict[str, Any]]:
    """테이블별 I/O 상위 N개를 dict 리스트로 반환한다. (PRD 섹션 13)"""
    sql = _load_query("table_io.sql")
    rows: List[Dict[str, Any]] = []
    try:
        with conn.cursor() as cur:
            cur.execute(sql, {"limit": int(top_n)})
            rows = list(cur.fetchall())
    except Exception as exc:  # noqa: BLE001 - PS 미활성/권한 부족 등 흡수
        logger.warning("Table I/O 수집 실패 (Performance Schema 확인 필요): %s", exc)
        return []

    logger.info("Collected %d table I/O rows", len(rows))
    return rows
