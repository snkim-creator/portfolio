"""SQLite 저장 로직. Snapshot / metrics / sql_digest_metrics 저장."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple

logger = logging.getLogger(__name__)


# SQLite INTEGER 는 부호있는 64bit. 이를 넘는 값(예: picosecond 타이머 누적)은
# 바인딩 시 OverflowError 가 나므로 float 로 저장한다.
_SQLITE_INT_MAX = 2**63 - 1


def _to_int(value):
    """정수화하되 64bit 초과 시 float 로 반환(오버플로 방지)."""
    try:
        i = int(value)
    except (TypeError, ValueError):
        return None
    if -_SQLITE_INT_MAX <= i <= _SQLITE_INT_MAX:
        return i
    return float(i)


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def create_snapshot(
    conn: sqlite3.Connection,
    server_info: Dict[str, Any],
    conn_endpoint: str | None = None,
) -> int:
    """snapshots 에 1행 추가하고 snapshot id 를 반환한다."""
    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """
        INSERT INTO snapshots
            (server_id, conn_endpoint, snapshot_time, db_version, db_flavor, hostname, uptime)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            server_info.get("server_id"),
            conn_endpoint,
            snapshot_time,
            server_info.get("version"),
            server_info.get("flavor"),
            server_info.get("hostname"),
            _to_int(server_info.get("uptime")),
        ),
    )
    conn.commit()
    snapshot_id = int(cur.lastrowid)
    logger.info("Snapshot saved (id=%d)", snapshot_id)
    return snapshot_id


def save_metrics(
    conn: sqlite3.Connection,
    snapshot_id: int,
    metrics: Iterable[Tuple[str, str, float]],
) -> int:
    """(name, type, value) 튜플 목록을 metrics 에 저장한다."""
    rows = [(snapshot_id, name, mtype, value) for (name, mtype, value) in metrics]
    conn.executemany(
        "INSERT INTO metrics (snapshot_id, metric_name, metric_type, metric_value) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def save_sql_digests(
    conn: sqlite3.Connection,
    snapshot_id: int,
    digests: List[Dict[str, Any]],
) -> int:
    """SQL Digest 조회 결과를 sql_digest_metrics 에 저장한다."""
    rows = []
    for d in digests:
        rows.append(
            (
                snapshot_id,
                d.get("SCHEMA_NAME"),
                d.get("DIGEST"),
                d.get("DIGEST_TEXT"),
                _to_int(d.get("COUNT_STAR")),
                _to_float(d.get("SUM_TIMER_WAIT")),
                _to_float(d.get("AVG_TIMER_WAIT")),
                _to_float(d.get("MIN_TIMER_WAIT")),
                _to_float(d.get("MAX_TIMER_WAIT")),
                _to_int(d.get("SUM_ROWS_EXAMINED")),
                _to_int(d.get("SUM_ROWS_SENT")),
                _to_int(d.get("SUM_ROWS_AFFECTED")),
                _to_int(d.get("SUM_CREATED_TMP_TABLES")),
                _to_int(d.get("SUM_CREATED_TMP_DISK_TABLES")),
                _to_int(d.get("SUM_SELECT_SCAN")),
                _to_int(d.get("SUM_SELECT_FULL_JOIN")),
                _to_int(d.get("SUM_NO_INDEX_USED")),
                _to_int(d.get("SUM_NO_GOOD_INDEX_USED")),
                str(d.get("FIRST_SEEN")) if d.get("FIRST_SEEN") is not None else None,
                str(d.get("LAST_SEEN")) if d.get("LAST_SEEN") is not None else None,
            )
        )

    conn.executemany(
        """
        INSERT INTO sql_digest_metrics (
            snapshot_id, schema_name, digest, digest_text,
            execution_count, total_latency, avg_latency, min_latency, max_latency,
            rows_examined, rows_sent, rows_affected,
            tmp_tables, tmp_disk_tables,
            select_scan, select_full_join, no_index_used, no_good_index_used,
            first_seen, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def save_table_io(
    conn: sqlite3.Connection,
    snapshot_id: int,
    table_io: List[Dict[str, Any]],
) -> int:
    """Table I/O 조회 결과를 table_io_metrics 에 저장한다."""
    rows = [
        (
            snapshot_id,
            r.get("OBJECT_SCHEMA"),
            r.get("OBJECT_NAME"),
            _to_int(r.get("COUNT_READ")),
            _to_int(r.get("COUNT_WRITE")),
            _to_float(r.get("SUM_TIMER_READ")),
            _to_float(r.get("SUM_TIMER_WRITE")),
        )
        for r in table_io
    ]
    conn.executemany(
        "INSERT INTO table_io_metrics (snapshot_id, object_schema, object_name, "
        "count_read, count_write, sum_timer_read, sum_timer_write) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)
