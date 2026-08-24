"""Analyzer 오케스트레이션: context 생성 → rule 실행 → Finding 저장. (PRD 섹션 20)"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List

from app.analyzer import baseline, baseline_stats, finding_lifecycle, rules, sql_regression

logger = logging.getLogger(__name__)


def analyze(
    conn: sqlite3.Connection, config: Dict[str, Any], endpoint: str | None = None
) -> Dict[str, Any]:
    """지정 서버(endpoint)의 최신 Snapshot 을 분석하여 Finding 을 생성/저장한다.

    endpoint(host:port) 가 주어지면 해당 서버의 최신 스냅샷만 대상으로 한다
    (다중 서버에서 '전역 최신' 오분석 방지). 없으면 전역 최신.
    """
    logger.info("Analyzer Start (endpoint=%s)", endpoint)

    ctx = baseline.build_context(conn, endpoint)
    if ctx is None:
        logger.warning(
            "분석할 Snapshot 이 없습니다 (endpoint=%s). 먼저 collect 를 실행하세요.", endpoint
        )
        return {"snapshot_id": None, "findings": [], "summary": {}}

    current = ctx["current"]
    snapshot_id = int(current["id"])

    if ctx["previous"] is None:
        logger.info(
            "이전 Snapshot 이 없어 GAUGE 기반 rule 만 평가합니다 "
            "(counter rate/delta rule 은 다음 수집 이후 가능)."
        )

    analyzer_cfg = config.get("analyzer", {}) if config else {}
    thresholds = analyzer_cfg.get("thresholds", {})

    # P2: 7d Baseline(median/p95) 계산해 컨텍스트에 주입 (Rule/Finding 이 근거 수치로 사용)
    base_cfg = analyzer_cfg.get("baseline", {})
    ctx["baselines"] = baseline_stats.compute(
        conn,
        current["conn_endpoint"],
        current,
        days=int(base_cfg.get("days", 7)),
        min_samples=int(base_cfg.get("min_samples", 20)),
    )

    findings: List[Dict[str, Any]] = []
    for rule in rules.ALL_RULES:
        try:
            findings.extend(rule(ctx, thresholds))
        except Exception as exc:  # noqa: BLE001 - 개별 rule 실패가 전체를 막지 않도록
            logger.warning("Rule %s 실행 실패: %s", getattr(rule, "__name__", rule), exc)

    # P3: SQL Regression 탐지 (기간 avg latency vs 7d 일별 median)
    try:
        window_hours = float(
            (config.get("report", {}) if config else {}).get("analysis_window_hours", 24)
        )
        findings.extend(
            sql_regression.detect(
                conn,
                current["conn_endpoint"],
                current,
                window_hours,
                thresholds.get("sql_regression", {}),
                baseline_days=int(base_cfg.get("days", 7)),
            )
        )
    except Exception as exc:  # noqa: BLE001 - 회귀 탐지 실패가 전체를 막지 않도록
        logger.warning("SQL Regression 탐지 실패: %s", exc)

    # severity 높은 순으로 정렬
    findings.sort(key=lambda f: rules.SEVERITY_ORDER.get(f["severity"], 0), reverse=True)

    # P4: Finding Lifecycle (NEW/PERSISTENT/RESOLVED). 저장 전 판정 → 저장 → 연속일수 채움.
    endpoint = current["conn_endpoint"]
    resolved: List[Dict[str, Any]] = []
    lifecycle_summary = {"new": 0, "persistent": 0, "resolved": 0}
    try:
        resolved, lifecycle_summary = finding_lifecycle.classify(conn, endpoint, current, findings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Finding lifecycle 판정 실패: %s", exc)

    _persist(conn, snapshot_id, findings)

    try:
        finding_lifecycle.fill_persist_days(conn, endpoint, current, findings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_days 계산 실패: %s", exc)

    summary = _summarize(findings)
    logger.info(
        "Finding Count: %d (critical=%d warning=%d info=%d) | lifecycle NEW=%d PERSISTENT=%d RESOLVED=%d",
        len(findings),
        summary.get("critical", 0),
        summary.get("warning", 0),
        summary.get("info", 0),
        lifecycle_summary["new"],
        lifecycle_summary["persistent"],
        lifecycle_summary["resolved"],
    )
    logger.info("Analyzer End")

    return {
        "snapshot_id": snapshot_id,
        "snapshot_time": current["snapshot_time"],
        "database": current["hostname"],
        "db_version": current["db_version"],
        "server_id": current["server_id"],
        "endpoint": current["conn_endpoint"],
        "findings": findings,
        "resolved": resolved,
        "lifecycle_summary": lifecycle_summary,
        "summary": summary,
        "interval_seconds": ctx["interval_seconds"],
        "counter_reset": ctx["counter_reset"],
        # Health 섹션(P5)용 컨텍스트
        "values": ctx["values"],
        "prev_values": ctx["prev_values"],
        "derived": ctx["derived"],
        "rate": ctx["rate"],
        "baselines": ctx["baselines"],
    }


def _persist(conn: sqlite3.Connection, snapshot_id: int, findings: List[Dict[str, Any]]) -> None:
    # 재분석 시 같은 snapshot 의 기존 finding 은 교체한다.
    conn.execute("DELETE FROM findings WHERE snapshot_id = ?", (snapshot_id,))
    rows = [
        (
            snapshot_id,
            f["category"],
            f["severity"],
            f["metric"],
            finding_lifecycle.finding_key(f),
            f["current"],
            f["baseline"],
            f["message"],
        )
        for f in findings
    ]
    conn.executemany(
        "INSERT INTO findings (snapshot_id, category, severity, metric, finding_key, "
        "current_value, baseline_value, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def _summarize(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        sev = f["severity"].lower()
        if sev in summary:
            summary[sev] += 1
    return summary
