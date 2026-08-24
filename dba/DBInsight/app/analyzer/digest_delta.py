"""SQL Digest 기간(window) Delta 계산. (개선요청 Priority 1)

events_statements_summary_by_digest 의 누적값을 '분석 기간 Delta' 로 변환한다.
- window baseline = 현재 스냅샷 기준 window_hours 이전에 가장 가까운(이하) 스냅샷.
  충분한 이력이 없으면 해당 서버의 가장 오래된 스냅샷으로 대체(부분 기간)한다.
- reset(현재값 < 이전값, 서버 재시작/PS reset) digest 는 음수 Delta 대신 reset 처리(랭킹 제외).
- top-N 만 저장하므로 두 스냅샷에 모두 존재하는 digest(교집합)에 대해서만 신뢰 가능한 Delta 를 낸다.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_PS_TO_MS = 1e9

# Delta 를 낼 누적 counter 컬럼
_DIGEST_COLS = (
    "execution_count",
    "total_latency",
    "rows_examined",
    "rows_sent",
    "rows_affected",
    "tmp_tables",
    "tmp_disk_tables",
    "select_scan",
    "select_full_join",
    "no_index_used",
    "no_good_index_used",
)

# DBA Top SQL 랭킹에서 제외할 Transaction/Session Control 문 (개선요청 §6)
_ADMIN_STMT_RE = re.compile(
    r"^\s*(COMMIT|ROLLBACK|BEGIN|START\s+TRANSACTION|SET\b|USE\b|SAVEPOINT|"
    r"RELEASE\b|LOCK\s+TABLES|UNLOCK\s+TABLES|FLUSH\b|SHOW\b)",
    re.IGNORECASE,
)


def is_admin_statement(digest_text: str) -> bool:
    """Top SQL 랭킹에서 제외할 TCL/세션 제어문 여부."""
    return bool(_ADMIN_STMT_RE.match(digest_text or ""))


def select_window_baseline(
    conn: sqlite3.Connection,
    endpoint: str,
    current_row: sqlite3.Row,
    window_hours: float,
) -> Tuple[Optional[sqlite3.Row], bool]:
    """(baseline_row, partial) 반환. partial=True 면 이력 부족으로 기간이 짧음."""
    conn.row_factory = sqlite3.Row
    try:
        target = (
            datetime.strptime(current_row["snapshot_time"], _TIME_FMT)
            - timedelta(hours=window_hours)
        ).strftime(_TIME_FMT)
    except (TypeError, ValueError):
        return None, False

    # 1) window 시작 시점 이전에 가장 가까운 스냅샷
    row = conn.execute(
        "SELECT * FROM snapshots WHERE conn_endpoint = ? AND id < ? AND snapshot_time <= ? "
        "ORDER BY snapshot_time DESC LIMIT 1",
        (endpoint, current_row["id"], target),
    ).fetchone()
    if row:
        return row, False

    # 2) 부족하면 해당 서버의 가장 오래된 스냅샷(부분 기간)
    row = conn.execute(
        "SELECT * FROM snapshots WHERE conn_endpoint = ? AND id < ? ORDER BY id ASC LIMIT 1",
        (endpoint, current_row["id"]),
    ).fetchone()
    if row:
        return row, True
    return None, False


def _load(conn: sqlite3.Connection, snapshot_id: int) -> Dict[str, sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    sql = (
        "SELECT digest, digest_text, " + ", ".join(_DIGEST_COLS)
        + " FROM sql_digest_metrics WHERE snapshot_id = ?"
    )
    return {r["digest"]: r for r in conn.execute(sql, (snapshot_id,)).fetchall() if r["digest"]}


def _num(v) -> float:
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def compute_period_digests(
    conn: sqlite3.Connection, current_id: int, baseline_id: int
) -> Dict[str, Any]:
    """두 스냅샷 사이의 digest별 기간 Delta + 파생값 리스트를 만든다."""
    cur = _load(conn, current_id)
    base = _load(conn, baseline_id)

    digests: List[Dict[str, Any]] = []
    reset_count = 0

    for dg, c in cur.items():
        b = base.get(dg)
        if b is None:
            continue  # 교집합만 신뢰(top-N 저장 한계)

        deltas: Dict[str, float] = {}
        reset = False
        for col in _DIGEST_COLS:
            dv = _num(c[col]) - _num(b[col])
            if dv < 0:  # reset (현재 < 이전) → 음수 delta 금지 (개선요청 §2)
                reset = True
                break
            deltas["delta_" + col] = dv
        if reset:
            reset_count += 1
            continue

        dcount = deltas["delta_execution_count"]
        dsum = deltas["delta_total_latency"]  # picoseconds
        dexam = deltas["delta_rows_examined"]
        dsent = deltas["delta_rows_sent"]
        dtmp = deltas["delta_tmp_tables"]

        if dcount <= 0:
            continue  # 기간 내 실행 없음 → 랭킹 의미 없음

        digests.append(
            {
                "digest": dg,
                "digest_text": c["digest_text"] or "",
                **deltas,
                "period_avg_latency_ms": round(dsum / dcount / _PS_TO_MS, 3),
                "period_rows_examined_per_exec": round(dexam / dcount, 1),
                "period_rows_examined_ratio": round(dexam / dsent, 1) if dsent > 0 else None,
                "period_tmp_disk_ratio": round(deltas["delta_tmp_disk_tables"] / dtmp, 3)
                if dtmp > 0
                else None,
            }
        )

    logger.info(
        "기간 Delta digest %d개 (reset 제외 %d개)", len(digests), reset_count
    )
    return {"digests": digests, "reset_count": reset_count}


def window_metric_deltas(
    conn: sqlite3.Connection, current_id: int, baseline_id: int, names: List[str]
) -> Dict[str, Optional[float]]:
    """지정 COUNTER metric 들의 window(현재-baseline) 구간 delta. reset(음수)은 None."""
    conn.row_factory = sqlite3.Row

    def _load(sid: int) -> Dict[str, float]:
        placeholders = ",".join("?" for _ in names)
        out: Dict[str, float] = {}
        for r in conn.execute(
            f"SELECT metric_name, metric_value FROM metrics "
            f"WHERE snapshot_id = ? AND metric_name IN ({placeholders})",
            (sid, *names),
        ):
            if r["metric_value"] is not None:
                out[r["metric_name"]] = float(r["metric_value"])
        return out

    cur, base = _load(current_id), _load(baseline_id)
    result: Dict[str, Optional[float]] = {}
    for n in names:
        if n in cur and n in base:
            d = cur[n] - base[n]
            result[n] = d if d >= 0 else None
    return result


def actual_window_hours(current_row: sqlite3.Row, baseline_row: sqlite3.Row) -> Optional[float]:
    try:
        c = datetime.strptime(current_row["snapshot_time"], _TIME_FMT)
        b = datetime.strptime(baseline_row["snapshot_time"], _TIME_FMT)
        return round((c - b).total_seconds() / 3600.0, 1)
    except (TypeError, ValueError):
        return None
