"""Finding Lifecycle (NEW / PERSISTENT / RESOLVED). (개선요청 §10~11)

직전에 분석된 스냅샷의 finding 집합과 현재를 비교한다.
- NEW: 이전엔 없던 finding 이 현재 발생
- PERSISTENT: 이전에도 있고 현재도 지속 (연속 발생 일수 포함)
- RESOLVED: 이전엔 WARNING/CRITICAL 이었으나 현재 사라짐

동일 finding 매칭은 finding_key(category:metric[:digest]) 로 한다.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DATE_FMT = "%Y-%m-%d"


def finding_key(f: Dict[str, Any]) -> str:
    base = f"{f.get('category')}:{f.get('metric')}"
    dg = f.get("digest")
    return f"{base}:{dg}" if dg else base


def _previous_snapshot_with_findings(
    conn: sqlite3.Connection, endpoint: str, current_id: int
) -> Optional[int]:
    row = conn.execute(
        "SELECT f.snapshot_id AS sid FROM findings f JOIN snapshots s ON s.id = f.snapshot_id "
        "WHERE s.conn_endpoint = ? AND f.snapshot_id < ? "
        "ORDER BY f.snapshot_id DESC LIMIT 1",
        (endpoint, current_id),
    ).fetchone()
    return row["sid"] if row else None


def _load_keys(conn: sqlite3.Connection, snapshot_id: int) -> Dict[str, Dict[str, Any]]:
    """{key: {severity, category, metric, description}}. 구버전 행은 category:metric 로 재구성."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in conn.execute(
        "SELECT finding_key, category, metric, severity, description "
        "FROM findings WHERE snapshot_id = ?",
        (snapshot_id,),
    ):
        key = r["finding_key"] or f"{r['category']}:{r['metric']}"
        out[key] = {
            "severity": r["severity"],
            "category": r["category"],
            "metric": r["metric"],
            "description": r["description"],
        }
    return out


def _persist_days(conn: sqlite3.Connection, endpoint: str, key: str, cur_date: str) -> int:
    """finding_key 가 나타난 날짜들 중 cur_date 에서 끝나는 연속 일수. (현재 스냅샷 저장 후 호출)"""
    rows = conn.execute(
        "SELECT DISTINCT substr(s.snapshot_time, 1, 10) AS d "
        "FROM findings f JOIN snapshots s ON s.id = f.snapshot_id "
        "WHERE s.conn_endpoint = ? AND f.finding_key = ?",
        (endpoint, key),
    ).fetchall()
    dset = {r["d"] for r in rows}
    if not dset:
        return 1
    try:
        d = datetime.strptime(cur_date, _DATE_FMT)
    except (TypeError, ValueError):
        return 1
    count = 0
    while d.strftime(_DATE_FMT) in dset:
        count += 1
        d -= timedelta(days=1)
    return max(count, 1)


def classify(
    conn: sqlite3.Connection, endpoint: str, current_row: sqlite3.Row, findings: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """현재 findings 에 lifecycle 표시(NEW/PERSISTENT+days)하고, RESOLVED 목록과 요약을 반환.

    NEW/PERSISTENT 판정은 저장 전에 수행하고, 연속 일수는 저장 후 별도로 채운다.
    """
    prev_id = _previous_snapshot_with_findings(conn, endpoint, current_row["id"])
    prev = _load_keys(conn, prev_id) if prev_id else {}

    cur_keys = set()
    for f in findings:
        k = finding_key(f)
        cur_keys.add(k)
        f["lifecycle"] = "PERSISTENT" if k in prev else "NEW"

    resolved: List[Dict[str, Any]] = []
    for k, info in prev.items():
        if k not in cur_keys and info["severity"] in ("WARNING", "CRITICAL"):
            resolved.append(
                {
                    "category": info["category"],
                    "metric": info["metric"],
                    "previous_severity": info["severity"],
                    "lifecycle": "RESOLVED",
                    "message": f"이전 {info['severity']} → 현재 정상 ({info['category']}/{info['metric']}).",
                }
            )

    summary = {
        "new": sum(1 for f in findings if f["lifecycle"] == "NEW"),
        "persistent": sum(1 for f in findings if f["lifecycle"] == "PERSISTENT"),
        "resolved": len(resolved),
    }
    return resolved, summary


def fill_persist_days(
    conn: sqlite3.Connection, endpoint: str, current_row: sqlite3.Row, findings: List[Dict[str, Any]]
) -> None:
    """저장 후 PERSISTENT finding 에 연속 일수를 채운다."""
    cur_date = str(current_row["snapshot_time"])[:10]
    for f in findings:
        if f.get("lifecycle") == "PERSISTENT":
            f["persist_days"] = _persist_days(conn, endpoint, finding_key(f), cur_date)
