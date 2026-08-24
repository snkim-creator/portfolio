"""GAUGE 지표의 기간 Baseline(7d median/p95/avg) 계산. (개선요청 P2)

- 대상: metrics 테이블의 GAUGE 지표 + 파생 ratio(connection_usage, dirty_page_ratio).
  COUNTER 누적값은 단조증가라 median/p95 가 무의미하므로 제외한다.
- 표본이 부족하면 status=INSUFFICIENT_DATA 로 반환하고, 프로그램은 실패하지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _stats(vals: List[float], min_samples: int) -> Dict[str, Any]:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return {"median": None, "p95": None, "avg": None, "samples": 0, "status": "INSUFFICIENT_DATA"}
    return {
        "median": _percentile(vals, 0.5),
        "p95": _percentile(vals, 0.95),
        "avg": sum(vals) / len(vals),
        "samples": len(vals),
        "status": "OK" if len(vals) >= min_samples else "INSUFFICIENT_DATA",
    }


def compute(
    conn: sqlite3.Connection,
    endpoint: str,
    current_row: sqlite3.Row,
    days: int = 7,
    min_samples: int = 20,
) -> Dict[str, Dict[str, Any]]:
    """{metric_name: {median,p95,avg,samples,status}} 반환 (해당 서버, 최근 days일, 현재 제외)."""
    conn.row_factory = sqlite3.Row
    try:
        cutoff = (
            datetime.strptime(current_row["snapshot_time"], _TIME_FMT) - timedelta(days=days)
        ).strftime(_TIME_FMT)
    except (TypeError, ValueError):
        return {}

    series: Dict[str, List[float]] = {}

    # 1) GAUGE 원지표 시계열
    for r in conn.execute(
        "SELECT m.metric_name AS name, m.metric_value AS val "
        "FROM metrics m JOIN snapshots s ON s.id = m.snapshot_id "
        "WHERE s.conn_endpoint = ? AND s.id <> ? AND s.snapshot_time >= ? "
        "AND m.metric_type = 'GAUGE'",
        (endpoint, current_row["id"], cutoff),
    ):
        if r["val"] is not None:
            series.setdefault(r["name"], []).append(float(r["val"]))

    # 2) 파생 ratio 시계열 (스냅샷별 구성요소로 계산)
    _add_derived_series(conn, endpoint, current_row["id"], cutoff, series)

    return {name: _stats(vals, min_samples) for name, vals in series.items()}


def _add_derived_series(
    conn: sqlite3.Connection,
    endpoint: str,
    current_id: int,
    cutoff: str,
    series: Dict[str, List[float]],
) -> None:
    """스냅샷별 GAUGE 구성요소로 connection_usage / dirty_page_ratio 시계열 생성."""
    components = (
        "Threads_connected",
        "max_connections",
        "Innodb_buffer_pool_pages_dirty",
        "Innodb_buffer_pool_pages_total",
    )
    placeholders = ",".join("?" for _ in components)
    per_snap: Dict[int, Dict[str, float]] = {}
    for r in conn.execute(
        "SELECT m.snapshot_id AS sid, m.metric_name AS name, m.metric_value AS val "
        "FROM metrics m JOIN snapshots s ON s.id = m.snapshot_id "
        f"WHERE s.conn_endpoint = ? AND s.id <> ? AND s.snapshot_time >= ? "
        f"AND m.metric_name IN ({placeholders})",
        (endpoint, current_id, cutoff, *components),
    ):
        if r["val"] is not None:
            per_snap.setdefault(r["sid"], {})[r["name"]] = float(r["val"])

    for vals in per_snap.values():
        tc, mc = vals.get("Threads_connected"), vals.get("max_connections")
        if tc is not None and mc:
            series.setdefault("connection_usage", []).append(tc / mc)
        pd, pt = vals.get("Innodb_buffer_pool_pages_dirty"), vals.get("Innodb_buffer_pool_pages_total")
        if pd is not None and pt:
            series.setdefault("dirty_page_ratio", []).append(pd / pt)
