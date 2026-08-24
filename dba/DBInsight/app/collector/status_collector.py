"""Global Status 수집. PRD 섹션 11 항목만 whitelist 로 저장한다.

각 metric 에 Type(GAUGE / COUNTER)을 부여한다. (PRD 섹션 16)
- GAUGE:  현재 상태값. 그대로 비교 가능.
- COUNTER: 서버 시작 이후 누적값. Delta/rate 계산이 필요.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

QUERIES_DIR = Path(__file__).resolve().parent.parent.parent / "queries" / "mysql"

# metric_name -> metric_type
# PRD 섹션 11 + 섹션 16 기준 분류.
METRIC_TYPES: Dict[str, str] = {
    # Connection
    "Threads_connected": "GAUGE",
    "Threads_running": "GAUGE",
    "Connections": "COUNTER",
    "Max_used_connections": "GAUGE",
    "Aborted_connects": "COUNTER",
    "Aborted_clients": "COUNTER",
    # Query
    "Queries": "COUNTER",
    "Questions": "COUNTER",
    "Slow_queries": "COUNTER",
    "Com_select": "COUNTER",
    "Com_insert": "COUNTER",
    "Com_update": "COUNTER",
    "Com_delete": "COUNTER",
    # InnoDB Buffer Pool
    "Innodb_buffer_pool_read_requests": "COUNTER",
    "Innodb_buffer_pool_reads": "COUNTER",
    "Innodb_buffer_pool_pages_total": "GAUGE",
    "Innodb_buffer_pool_pages_free": "GAUGE",
    "Innodb_buffer_pool_pages_dirty": "GAUGE",
    "Innodb_buffer_pool_wait_free": "COUNTER",  # buffer pool 여유 대기 (InnoDB Health §15)
    "Innodb_log_waits": "COUNTER",              # 로그 버퍼 대기 (InnoDB Health §15)
    # InnoDB I/O
    "Innodb_data_reads": "COUNTER",
    "Innodb_data_writes": "COUNTER",
    "Innodb_data_read": "COUNTER",
    "Innodb_data_written": "COUNTER",
    "Innodb_data_fsyncs": "COUNTER",
    # Row Operations (InnoDB) — 일부 MariaDB 빌드는 미노출 → 없으면 skip
    "Innodb_rows_read": "COUNTER",
    "Innodb_rows_inserted": "COUNTER",
    "Innodb_rows_updated": "COUNTER",
    "Innodb_rows_deleted": "COUNTER",
    # Row Operations (Handler) — MySQL/MariaDB 공통. 스토리지 엔진 무관 행 접근/변경 지표.
    "Handler_read_first": "COUNTER",   # 인덱스 첫 엔트리 읽기(풀 인덱스 스캔 신호)
    "Handler_read_key": "COUNTER",     # 인덱스 기반 행 읽기(좋음)
    "Handler_read_next": "COUNTER",
    "Handler_read_prev": "COUNTER",
    "Handler_read_rnd": "COUNTER",
    "Handler_read_rnd_next": "COUNTER",  # 풀 테이블 스캔 신호(높으면 인덱스 부재 의심)
    "Handler_write": "COUNTER",
    "Handler_update": "COUNTER",
    "Handler_delete": "COUNTER",
    "Handler_commit": "COUNTER",
    "Handler_rollback": "COUNTER",
    # Lock
    "Innodb_row_lock_current_waits": "GAUGE",
    "Innodb_row_lock_time": "COUNTER",
    "Innodb_row_lock_time_max": "GAUGE",
    "Innodb_row_lock_waits": "COUNTER",
    # Temporary Table
    "Created_tmp_tables": "COUNTER",
    "Created_tmp_disk_tables": "COUNTER",
    # Table Cache
    "Opened_tables": "COUNTER",
    "Open_tables": "GAUGE",
    "Table_open_cache_hits": "COUNTER",
    "Table_open_cache_misses": "COUNTER",
    # Replication (master 측: 연결된 replica 수 — MariaDB. MySQL 엔 없어 자동 skip)
    "Slaves_connected": "GAUGE",
}


def _load_query(name: str) -> str:
    return (QUERIES_DIR / name).read_text(encoding="utf-8")


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def collect_global_status(conn) -> List[Tuple[str, str, float]]:
    """Whitelist 에 해당하는 Global Status 항목을 (name, type, value) 리스트로 반환.

    SHOW GLOBAL STATUS 는 variable_name 대소문자가 서버마다 다를 수 있어
    대소문자 무시 매칭을 사용한다.
    """
    sql = _load_query("global_status.sql")
    raw: Dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute(sql)
        for row in cur.fetchall():
            # DictCursor: {'Variable_name': ..., 'Value': ...}
            var = row.get("Variable_name")
            val = row.get("Value")
            if var is not None:
                raw[str(var).lower()] = val

    results: List[Tuple[str, str, float]] = []
    for name, mtype in METRIC_TYPES.items():
        value = _to_float(raw.get(name.lower()))
        if value is None:
            logger.debug("Global status metric 없음/NULL: %s", name)
            continue
        results.append((name, mtype, value))

    logger.info("Collected %d metrics", len(results))
    return results
