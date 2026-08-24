"""Baseline / Delta / Counter rate / Derived metric 계산. (PRD 섹션 15~17)

MVP 1차 baseline = 바로 이전 Snapshot 값.
COUNTER 타입은 단순 현재값 비교가 아니라 구간 rate(초당 증가량)를 계산한다. (PRD 섹션 16)
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def get_latest_two_snapshots(
    conn: sqlite3.Connection, endpoint: Optional[str] = None
) -> Tuple[Optional[sqlite3.Row], Optional[sqlite3.Row]]:
    """(current, previous) Snapshot 을 반환.

    - endpoint(host:port) 가 주어지면 그 접속 대상의 최신 Snapshot 을 current 로 삼는다.
      (다중 서버 환경에서 '전역 최신'이 아니라 해당 서버를 리포트하도록)
    - previous 는 current 와 **같은 server_id** 의 바로 이전 Snapshot. (서버 간 counter 비교 방지)
    """
    conn.row_factory = sqlite3.Row
    if endpoint:
        current = conn.execute(
            "SELECT * FROM snapshots WHERE conn_endpoint = ? ORDER BY id DESC LIMIT 1",
            (endpoint,),
        ).fetchone()
    else:
        current = conn.execute(
            "SELECT * FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if current is None:
        return None, None

    previous = conn.execute(
        "SELECT * FROM snapshots WHERE server_id IS ? AND id < ? "
        "ORDER BY id DESC LIMIT 1",
        (current["server_id"], current["id"]),
    ).fetchone()
    return current, previous


def load_metrics(conn: sqlite3.Connection, snapshot_id: int) -> Dict[str, Dict[str, Any]]:
    """{metric_name: {"type": ..., "value": ...}} 형태로 로드."""
    result: Dict[str, Dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT metric_name, metric_type, metric_value FROM metrics WHERE snapshot_id = ?",
        (snapshot_id,),
    ):
        result[row[0]] = {"type": row[1], "value": row[2]}
    return result


# performance_schema timer 단위: picosecond → millisecond
_PS_TO_MS = 1e9


def load_digests(conn: sqlite3.Connection, snapshot_id: int) -> Dict[str, sqlite3.Row]:
    """{digest: Row} 형태로 SQL Digest 를 로드."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT digest, digest_text, schema_name, execution_count, avg_latency, "
        "rows_examined, rows_sent FROM sql_digest_metrics WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchall()
    return {r["digest"]: r for r in rows if r["digest"]}


def _build_digests(
    cur_digests: Dict[str, sqlite3.Row], prev_digests: Dict[str, sqlite3.Row]
) -> list:
    """현재 digest 목록에 이전 스냅샷의 평균 지연을 붙여 SQL rule 용 리스트 생성."""
    result = []
    for dg, row in cur_digests.items():
        prev = prev_digests.get(dg)
        avg_ms = row["avg_latency"] / _PS_TO_MS if row["avg_latency"] else None
        prev_avg_ms = (
            prev["avg_latency"] / _PS_TO_MS if prev and prev["avg_latency"] else None
        )
        result.append(
            {
                "digest": dg,
                "digest_text": row["digest_text"],
                "schema_name": row["schema_name"],
                "execution_count": row["execution_count"],
                "avg_latency_ms": round(avg_ms, 3) if avg_ms is not None else None,
                "prev_avg_latency_ms": round(prev_avg_ms, 3) if prev_avg_ms is not None else None,
                "rows_examined": row["rows_examined"],
                "rows_sent": row["rows_sent"],
            }
        )
    return result


def _seconds_between(cur_time: str, prev_time: str) -> Optional[float]:
    try:
        c = datetime.strptime(cur_time, _TIME_FMT)
        p = datetime.strptime(prev_time, _TIME_FMT)
        secs = (c - p).total_seconds()
        return secs if secs > 0 else None
    except (TypeError, ValueError):
        return None


def _safe_div(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
    """0 또는 None 분모를 방어한 나눗셈. (PRD 섹션 28: Division by Zero)"""
    if numer is None or denom is None or denom == 0:
        return None
    return numer / denom


def build_context(
    conn: sqlite3.Connection, endpoint: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """분석에 필요한 모든 파생값을 담은 context dict 를 만든다.

    반환 dict:
      current, previous            : snapshot Row (previous 는 None 일 수 있음)
      interval_seconds             : 구간 길이(초) 또는 None
      cur_val(name), prev_val(name): 헬퍼 대신 아래 dict 로 제공
      values                       : {name: current_value}
      prev_values                  : {name: previous_value}
      rate                         : {name: 초당 증가율}  (COUNTER, reset 시 None)
      delta                        : {name: current-previous}
      delta_pct                    : {name: 변화율 %}
      derived                      : {파생지표명: 값}
      counter_reset                : bool (COUNTER 감소 감지 시 True)
    """
    current, previous = get_latest_two_snapshots(conn, endpoint)
    if current is None:
        return None

    cur_metrics = load_metrics(conn, current["id"])
    prev_metrics = load_metrics(conn, previous["id"]) if previous else {}

    values = {name: m["value"] for name, m in cur_metrics.items()}
    prev_values = {name: m["value"] for name, m in prev_metrics.items()}
    types = {name: m["type"] for name, m in cur_metrics.items()}

    interval = (
        _seconds_between(current["snapshot_time"], previous["snapshot_time"])
        if previous
        else None
    )

    rate: Dict[str, Optional[float]] = {}
    delta: Dict[str, Optional[float]] = {}
    delta_pct: Dict[str, Optional[float]] = {}
    counter_reset = False

    for name, cur_v in values.items():
        prev_v = prev_values.get(name)
        if prev_v is None or cur_v is None:
            continue
        d = cur_v - prev_v
        delta[name] = d
        delta_pct[name] = _safe_div(d, abs(prev_v))
        if delta_pct[name] is not None:
            delta_pct[name] *= 100.0

        if types.get(name) == "COUNTER":
            if d < 0:
                # 서버 재시작 등으로 counter 초기화 → rate 계산 불가 (PRD 섹션 28)
                counter_reset = True
                rate[name] = None
                logger.warning("Counter reset 감지: %s (%.0f -> %.0f)", name, prev_v, cur_v)
            elif interval:
                rate[name] = d / interval

    derived = _compute_derived(values, delta)

    cur_digests = load_digests(conn, current["id"])
    prev_digests = load_digests(conn, previous["id"]) if previous else {}
    digests = _build_digests(cur_digests, prev_digests)

    return {
        "current": current,
        "previous": previous,
        "interval_seconds": interval,
        "values": values,
        "prev_values": prev_values,
        "types": types,
        "rate": rate,
        "delta": delta,
        "delta_pct": delta_pct,
        "derived": derived,
        "digests": digests,
        "counter_reset": counter_reset,
    }


def _compute_derived(
    values: Dict[str, Any], delta: Dict[str, Optional[float]]
) -> Dict[str, Optional[float]]:
    """PRD 섹션 17 파생 지표. GAUGE 는 현재값, 비율성 counter 는 구간 delta 사용."""
    derived: Dict[str, Optional[float]] = {}

    # Connection Usage = Threads_connected / max_connections (현재값)
    derived["connection_usage"] = _safe_div(
        values.get("Threads_connected"), values.get("max_connections")
    )

    # Dirty Page Ratio = pages_dirty / pages_total (현재값)
    derived["dirty_page_ratio"] = _safe_div(
        values.get("Innodb_buffer_pool_pages_dirty"),
        values.get("Innodb_buffer_pool_pages_total"),
    )

    # Buffer Pool Hit Ratio = 1 - reads/read_requests (구간 delta 우선)
    d_reads = delta.get("Innodb_buffer_pool_reads")
    d_reqs = delta.get("Innodb_buffer_pool_read_requests")
    miss = _safe_div(d_reads, d_reqs)
    derived["buffer_pool_hit_ratio"] = (1 - miss) if miss is not None else None

    # Temporary Disk Table Ratio = disk / all (구간 delta 우선)
    derived["tmp_disk_table_ratio"] = _safe_div(
        delta.get("Created_tmp_disk_tables"), delta.get("Created_tmp_tables")
    )

    return derived
