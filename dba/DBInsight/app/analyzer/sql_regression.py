"""SQL Regression 탐지. (개선요청 §8, Priority 3)

'예전엔 빠르던 SQL 이 최근 느려진' 경우를 탐지한다.
- current: 분석 기간(window) 의 digest별 period_avg_latency (P1)
- baseline: 최근 baseline_days 일을 하루 단위로 나눠 구한 daily period_avg_latency 의 median (P2 방식)
- 규칙: current_avg >= baseline_median * ratio AND 기간 실행수 >= min_executions

digest별 avg latency 는 '실행당(per-exec)' 값이라 window 길이와 무관하게 비교 가능하다.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.analyzer import baseline_stats, digest_delta

logger = logging.getLogger(__name__)

_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_PS_TO_MS = 1e9


def _load_counts(conn: sqlite3.Connection, snapshot_id: int) -> Dict[str, Dict[str, float]]:
    """{digest: {count, sum(ps), exam}} 로드."""
    conn.row_factory = sqlite3.Row
    out: Dict[str, Dict[str, float]] = {}
    for r in conn.execute(
        "SELECT digest, execution_count, total_latency, rows_examined "
        "FROM sql_digest_metrics WHERE snapshot_id = ?",
        (snapshot_id,),
    ):
        if r["digest"]:
            out[r["digest"]] = {
                "count": float(r["execution_count"] or 0),
                "sum": float(r["total_latency"] or 0),
                "exam": float(r["rows_examined"] or 0),
            }
    return out


def _daily_anchor_ids(
    conn: sqlite3.Connection, endpoint: str, current_row: sqlite3.Row, days: int
) -> List[int]:
    """현재 기준 24h 간격 anchor 스냅샷 id 목록(최신→과거). 현재 window 이전 구간만."""
    try:
        base_time = datetime.strptime(current_row["snapshot_time"], _TIME_FMT)
    except (TypeError, ValueError):
        return []
    ids: List[int] = []
    for k in range(1, days + 2):  # now-24h, now-48h, ... (현재 24h window 제외)
        target = (base_time - timedelta(hours=24 * k)).strftime(_TIME_FMT)
        row = conn.execute(
            "SELECT id FROM snapshots WHERE conn_endpoint = ? AND id < ? AND snapshot_time <= ? "
            "ORDER BY snapshot_time DESC LIMIT 1",
            (endpoint, current_row["id"], target),
        ).fetchone()
        if row and (not ids or ids[-1] != row["id"]):
            ids.append(row["id"])
    return ids


def compute_digest_baseline(
    conn: sqlite3.Connection, endpoint: str, current_row: sqlite3.Row, days: int
) -> Dict[str, Dict[str, Any]]:
    """digest별 daily period avg latency / rows_examined-per-exec 의 median 등 baseline."""
    anchors = _daily_anchor_ids(conn, endpoint, current_row, days)
    if len(anchors) < 2:
        return {}

    # 인접 anchor 쌍(older, newer)마다 digest별 하루치 period 값 계산
    lat_series: Dict[str, List[float]] = {}
    rpe_series: Dict[str, List[float]] = {}
    maps = {sid: _load_counts(conn, sid) for sid in anchors}
    for i in range(len(anchors) - 1):
        newer, older = maps[anchors[i]], maps[anchors[i + 1]]
        for dg, c in newer.items():
            b = older.get(dg)
            if not b:
                continue
            dcount = c["count"] - b["count"]
            dsum = c["sum"] - b["sum"]
            dexam = c["exam"] - b["exam"]
            if dcount <= 0 or dsum < 0:  # reset/무실행 구간 제외
                continue
            lat_series.setdefault(dg, []).append(dsum / dcount / _PS_TO_MS)
            rpe_series.setdefault(dg, []).append(dexam / dcount)

    result: Dict[str, Dict[str, Any]] = {}
    for dg, lats in lat_series.items():
        s = sorted(lats)
        rpe = sorted(rpe_series.get(dg, []))
        result[dg] = {
            "avg_latency_median_ms": baseline_stats._percentile(s, 0.5),
            "rows_exam_per_exec_median": baseline_stats._percentile(rpe, 0.5) if rpe else None,
            "samples": len(s),
            "status": "OK" if len(s) >= 1 else "INSUFFICIENT_DATA",
        }
    return result


def detect(
    conn: sqlite3.Connection,
    endpoint: str,
    current_row: sqlite3.Row,
    window_hours: float,
    cfg: Dict[str, Any],
    baseline_days: int,
) -> List[Dict[str, Any]]:
    """SQL Regression Finding 리스트 반환."""
    latency_ratio = cfg.get("latency_ratio", 3.0)
    min_exec = cfg.get("min_executions", 100)
    min_days = cfg.get("min_baseline_days", 3)
    top_n = cfg.get("top_n", 10)

    window_base, _ = digest_delta.select_window_baseline(conn, endpoint, current_row, window_hours)
    if window_base is None:
        return []

    period = digest_delta.compute_period_digests(conn, current_row["id"], window_base["id"])
    cur_map = {d["digest"]: d for d in period["digests"]}
    base_map = compute_digest_baseline(conn, endpoint, current_row, baseline_days)

    candidates: List[Dict[str, Any]] = []
    for dg, c in cur_map.items():
        if digest_delta.is_admin_statement(c["digest_text"]):
            continue
        if c["delta_execution_count"] < min_exec:
            continue
        b = base_map.get(dg)
        if not b or b["status"] != "OK" or b["samples"] < min_days:
            continue
        cur_avg = c["period_avg_latency_ms"]
        base_avg = b["avg_latency_median_ms"]
        if cur_avg is None or not base_avg or base_avg <= 0:
            continue
        ratio = cur_avg / base_avg
        if ratio < latency_ratio:
            continue
        candidates.append((ratio, c, b))

    candidates.sort(key=lambda x: x[0], reverse=True)

    findings: List[Dict[str, Any]] = []
    for ratio, c, b in candidates[:top_n]:
        cur_rpe = c.get("period_rows_examined_per_exec")
        base_rpe = b.get("rows_exam_per_exec_median")
        rpe_note = ""
        if cur_rpe is not None and base_rpe:
            rpe_note = f" · 검사행/실행 {base_rpe:.0f}→{cur_rpe:.0f}"
        findings.append(
            {
                "category": "sql_regression",
                "metric": "avg_latency_regression",
                "severity": "WARNING",
                "current": c["period_avg_latency_ms"],
                "baseline": round(b["avg_latency_median_ms"], 3),
                "message": (
                    f"평균 실행시간이 평소 대비 {ratio:.1f}배 악화됐습니다 "
                    f"(7d median {b['avg_latency_median_ms']:.2f}ms → 최근 {c['period_avg_latency_ms']:.2f}ms, "
                    f"기간 실행 {int(c['delta_execution_count']):,}회{rpe_note}). "
                    f"digest: {(c['digest_text'] or '')[:80]}"
                ),
                # 근거 수치 (§9) + 리포트 SQL Regression 섹션용
                "digest": c.get("digest"),
                "digest_text": c["digest_text"],
                "avg_latency_current_ms": c["period_avg_latency_ms"],
                "avg_latency_baseline_ms": round(b["avg_latency_median_ms"], 3),
                "latency_change_ratio": round(ratio, 2),
                "execution_count": int(c["delta_execution_count"]),
                "rows_examined_per_exec_current": cur_rpe,
                "rows_examined_per_exec_baseline": round(base_rpe, 1) if base_rpe is not None else None,
                "baseline_samples": b["samples"],
            }
        )

    logger.info("SQL Regression %d건 탐지", len(findings))
    return findings
