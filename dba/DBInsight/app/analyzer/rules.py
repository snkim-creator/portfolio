"""Rule Engine. LLM 호출 전에 Python 으로 이상 여부를 판단한다. (PRD 섹션 18~19)

각 rule 은 context + thresholds 를 받아 Finding dict 를 0개 또는 1개 반환한다.
Finding 구조 (PRD 섹션 18):
    {category, metric, severity, current, baseline, message}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Severity (PRD 섹션 18)
NORMAL = "NORMAL"
INFO = "INFO"
WARNING = "WARNING"
CRITICAL = "CRITICAL"

SEVERITY_ORDER = {NORMAL: 0, INFO: 1, WARNING: 2, CRITICAL: 3}


def _finding(
    category: str,
    metric: str,
    severity: str,
    current: Optional[float],
    baseline: Optional[float],
    message: str,
    **extra: Any,
) -> Dict[str, Any]:
    """Finding dict. extra 로 previous/baseline_median/baseline_p95/change_vs_median/
    threshold/baseline_status 등 근거 수치를 덧붙인다. (개선요청 §9)"""
    finding = {
        "category": category,
        "metric": metric,
        "severity": severity,
        "current": current,
        "baseline": baseline,
        "message": message,
    }
    for k, v in extra.items():
        if v is not None:
            finding[k] = v
    return finding


def _baseline_fields(
    ctx: Dict[str, Any],
    baseline_key: str,
    current: Optional[float],
    previous: Optional[float] = None,
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """ctx['baselines'] 에서 median/p95 를 꺼내 Finding extra 필드로 만든다. (P2)"""
    out: Dict[str, Any] = {"previous": previous, "threshold": threshold}
    b = (ctx.get("baselines") or {}).get(baseline_key)
    if b and b.get("status") == "OK":
        median = b.get("median")
        out["baseline_median"] = round(median, 4) if median is not None else None
        out["baseline_p95"] = round(b["p95"], 4) if b.get("p95") is not None else None
        if median and current is not None and median != 0:
            out["change_vs_median"] = round(current / median, 2)
    elif b:
        out["baseline_status"] = b.get("status")
    return out


def rule_connection_usage(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    usage = ctx["derived"].get("connection_usage")
    if usage is None:
        return []
    t = th.get("connection_usage", {})
    if usage >= t.get("critical", 0.90):
        sev = CRITICAL
    elif usage >= t.get("warning", 0.80):
        sev = WARNING
    elif usage >= t.get("info", 0.70):
        sev = INFO
    else:
        return []
    bf = _baseline_fields(ctx, "connection_usage", usage, threshold=t.get("warning", 0.80))
    base_note = ""
    if "baseline_median" in bf and bf["baseline_median"] is not None:
        base_note = f" (7d median {bf['baseline_median'] * 100:.1f}%, p95 {(bf.get('baseline_p95') or 0) * 100:.1f}%)"
    return [
        _finding(
            "connection",
            "connection_usage",
            sev,
            round(usage * 100, 1),
            None,
            f"Connection 사용률이 {usage * 100:.1f}% 입니다{base_note} "
            f"(Threads_connected={ctx['values'].get('Threads_connected'):.0f} / "
            f"max_connections={ctx['values'].get('max_connections'):.0f}).",
            **bf,
        )
    ]


def rule_threads_running_spike(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    cur = ctx["values"].get("Threads_running")
    if cur is None:
        return []
    prev = ctx["prev_values"].get("Threads_running")

    # P2: 7d median 을 baseline 으로 우선 사용, 없으면 이전 Snapshot 값으로 폴백
    b = (ctx.get("baselines") or {}).get("Threads_running")
    if b and b.get("status") == "OK" and b.get("median") is not None:
        base = b["median"]
        base_label = f"7d median {base:.1f}"
    elif prev is not None:
        base = prev
        base_label = f"이전 {base:.0f}"
    else:
        return []

    t = th.get("threads_running", {})
    ratio = t.get("spike_ratio", 3)
    min_abs = t.get("min_absolute", 10)
    if base > 0 and cur >= base * ratio and cur >= min_abs:
        return [
            _finding(
                "connection",
                "threads_running",
                WARNING,
                cur,
                round(base, 2),
                f"Threads_running 이 급증했습니다 ({base_label} → 현재 {cur:.0f}, "
                f"기준 {ratio}배 & 최소 {min_abs} 이상).",
                **_baseline_fields(ctx, "Threads_running", cur, previous=prev),
            )
        ]
    return []


def rule_tmp_disk_ratio(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    ratio = ctx["derived"].get("tmp_disk_table_ratio")
    if ratio is None:
        return []
    warn = th.get("tmp_disk_table_ratio", {}).get("warning", 0.20)
    if ratio >= warn:
        return [
            _finding(
                "query",
                "tmp_disk_table_ratio",
                WARNING,
                round(ratio, 3),
                warn,
                f"디스크 임시테이블 비율이 {ratio * 100:.1f}% 입니다 "
                f"(구간 내 Created_tmp_disk_tables/Created_tmp_tables). "
                f"정렬/그룹핑 쿼리나 tmp_table_size 설정 확인이 필요할 수 있습니다.",
            )
        ]
    return []


def rule_buffer_pool_hit(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    hit = ctx["derived"].get("buffer_pool_hit_ratio")
    if hit is None:
        return []
    t = th.get("buffer_pool_hit_ratio", {})
    warn = t.get("warning", 0.95)
    info = t.get("info", 0.99)
    if hit < warn:
        sev = WARNING
    elif hit < info:
        sev = INFO
    else:
        return []
    return [
        _finding(
            "innodb",
            "buffer_pool_hit_ratio",
            sev,
            round(hit, 4),
            info,
            f"InnoDB Buffer Pool Hit Ratio 가 {hit * 100:.2f}% 입니다 "
            f"(구간 기준). 물리 읽기가 늘고 있는지 확인이 필요합니다.",
        )
    ]


def rule_dirty_page_ratio(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    ratio = ctx["derived"].get("dirty_page_ratio")
    if ratio is None:
        return []
    warn = th.get("dirty_page_ratio", {}).get("warning", 0.75)
    if ratio >= warn:
        return [
            _finding(
                "innodb",
                "dirty_page_ratio",
                WARNING,
                round(ratio, 3),
                warn,
                f"Dirty Page 비율이 {ratio * 100:.1f}% 입니다. "
                f"체크포인트/flush 부하를 확인하세요.",
                **_baseline_fields(ctx, "dirty_page_ratio", ratio, threshold=warn),
            )
        ]
    return []


def rule_slow_query_rate(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    rate = ctx["rate"].get("Slow_queries")
    if rate is None:
        return []
    warn = th.get("slow_query_rate", {}).get("warning", 0.5)
    if rate >= warn:
        return [
            _finding(
                "query",
                "slow_query_rate",
                WARNING,
                round(rate, 3),
                warn,
                f"Slow Query 가 초당 {rate:.2f}건 발생하고 있습니다 (구간 평균). "
                f"Top SQL 및 slow query log 확인이 필요합니다.",
            )
        ]
    return []


# 하나의 SQL rule 이 만들 수 있는 Finding 최대 개수 (LLM payload/노이즈 제한)
MAX_SQL_FINDINGS = 5


def _short(text: str, n: int = 90) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:n] + ("…" if len(text) > n else "")


def rule_sql_rows_examined(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    """검사행/전송행 비율이 큰 비효율 SQL 탐지. (PRD 섹션 19)

    누적값 기반이므로 rows_examined/rows_sent 는 해당 digest 의 평생 평균 비율.
    """
    t = th.get("sql_rows_examined", {})
    ratio_th = t.get("ratio", 100)
    min_exec = t.get("min_executions", 1000)

    candidates = []
    for d in ctx.get("digests", []):
        exec_c = d.get("execution_count") or 0
        sent = d.get("rows_sent") or 0
        examined = d.get("rows_examined") or 0
        if exec_c < min_exec or sent <= 0:  # rows_sent=0 은 비율 계산 불가 (PRD 섹션 17)
            continue
        ratio = examined / sent
        if ratio >= ratio_th:
            candidates.append((ratio, d))

    candidates.sort(key=lambda x: x[0], reverse=True)
    findings = []
    for ratio, d in candidates[:MAX_SQL_FINDINGS]:
        findings.append(
            _finding(
                "sql",
                "rows_examined_ratio",
                WARNING,
                round(ratio, 1),
                ratio_th,
                f"검사행/전송행 비율이 {ratio:,.0f}:1 입니다 "
                f"(실행 {exec_fmt(d)}회, 평균 {d.get('avg_latency_ms')}ms). "
                f"인덱스 미사용/비효율 쿼리 가능성. digest: {_short(d['digest_text'])}",
                digest=d.get("digest"),
            )
        )
    return findings


def rule_sql_latency_spike(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    """이전 스냅샷 대비 평균 지연이 급증한 SQL 탐지. (PRD 섹션 19)"""
    t = th.get("sql_latency_spike", {})
    inc_th = t.get("increase_ratio", 3.0)
    min_exec = t.get("min_executions", 100)

    candidates = []
    for d in ctx.get("digests", []):
        cur = d.get("avg_latency_ms")
        prev = d.get("prev_avg_latency_ms")
        exec_c = d.get("execution_count") or 0
        if cur is None or prev is None or prev <= 0 or exec_c < min_exec:
            continue
        inc = cur / prev
        if inc >= inc_th:
            candidates.append((inc, d))

    candidates.sort(key=lambda x: x[0], reverse=True)
    findings = []
    for inc, d in candidates[:MAX_SQL_FINDINGS]:
        findings.append(
            _finding(
                "sql",
                "sql_latency_spike",
                WARNING,
                d.get("avg_latency_ms"),
                d.get("prev_avg_latency_ms"),
                f"평균 지연이 이전 스냅샷 대비 {inc:.1f}배 증가 "
                f"({d.get('prev_avg_latency_ms')}ms → {d.get('avg_latency_ms')}ms, "
                f"실행 {exec_fmt(d)}회). digest: {_short(d['digest_text'])}",
                digest=d.get("digest"),
            )
        )
    return findings


def exec_fmt(d: Dict[str, Any]) -> str:
    c = d.get("execution_count")
    return f"{c:,}" if isinstance(c, int) else str(c)


def rule_lock_wait(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    waits = ctx["values"].get("Innodb_row_lock_current_waits")
    if waits is None:
        return []
    warn = th.get("lock_wait", {}).get("warning", 1)
    if waits >= warn:
        return [
            _finding(
                "lock",
                "innodb_row_lock_current_waits",
                WARNING,
                waits,
                0,
                f"현재 대기 중인 row lock 이 {waits:.0f}건 있습니다. "
                f"Lock 경합 트랜잭션 확인이 필요합니다.",
            )
        ]
    return []


def rule_long_transaction(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    """오래 실행 중인 트랜잭션 탐지. (PRD 섹션 19)"""
    secs = ctx["values"].get("innodb_trx_longest_seconds")
    if secs is None:
        return []
    t = th.get("long_transaction", {})
    crit = t.get("critical", 300)
    warn = t.get("warning", 60)
    if secs >= crit:
        sev = CRITICAL
    elif secs >= warn:
        sev = WARNING
    else:
        return []
    return [
        _finding(
            "transaction",
            "longest_transaction_seconds",
            sev,
            round(secs, 0),
            warn,
            f"실행 중인 가장 오래된 트랜잭션이 {secs:.0f}초째 진행 중입니다. "
            f"미완료 트랜잭션은 undo/History List 증가와 락 경합을 유발할 수 있어 확인이 필요합니다.",
        )
    ]


def rule_replication(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    """복제 상태 이상 탐지. (복제 replica 서버)"""
    v = ctx["values"]
    if v.get("replica_is_replica") != 1:
        return []  # 복제 replica 아님(마스터/단독)

    findings: List[Dict[str, Any]] = []
    io = v.get("replica_io_running")
    sql = v.get("replica_sql_running")
    if io == 0 or sql == 0:
        findings.append(
            _finding(
                "replication",
                "replica_thread_stopped",
                CRITICAL,
                0,
                1,
                f"복제 스레드가 중단됐습니다 (IO={'정상' if io == 1 else '중단'}, "
                f"SQL={'정상' if sql == 1 else '중단'}). "
                f"`SHOW REPLICA STATUS` 로 Last_Error 를 확인하세요.",
            )
        )

    errno = v.get("replica_last_errno")
    if errno and errno != 0:
        findings.append(
            _finding(
                "replication",
                "replica_last_errno",
                CRITICAL,
                errno,
                0,
                f"복제 에러가 있습니다 (errno={int(errno)}). "
                f"`SHOW REPLICA STATUS` 의 Last_Error 원문 확인이 필요합니다.",
            )
        )

    behind = v.get("replica_seconds_behind")
    if behind is not None:
        t = th.get("replication", {})
        warn = t.get("lag_warning", 30)
        crit = t.get("lag_critical", 300)
        sev = CRITICAL if behind >= crit else (WARNING if behind >= warn else None)
        if sev:
            findings.append(
                _finding(
                    "replication",
                    "replica_seconds_behind",
                    sev,
                    behind,
                    warn,
                    f"복제 지연이 {int(behind)}초입니다. "
                    f"마스터 부하/대용량 트랜잭션/네트워크 또는 replica 적용 지연 가능성.",
                    **_baseline_fields(ctx, "replica_seconds_behind", behind, threshold=warn),
                )
            )
    return findings


def rule_history_list_length(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    """InnoDB History List Length 급증 탐지. (개선요청 §16)

    HLL 은 워크로드마다 정상 범위가 크게 달라 절대 임계 대신 7d median 대비 배수를 우선 사용한다.
    """
    hll = ctx["values"].get("innodb_history_list_length")
    if hll is None:
        return []
    t = th.get("history_list_length", {})
    ratio = t.get("warning_ratio", 3)
    min_abs = t.get("min_absolute", 10000)
    crit_abs = t.get("critical_absolute")

    b = (ctx.get("baselines") or {}).get("innodb_history_list_length")
    median = b["median"] if (b and b.get("status") == "OK") else None

    sev = None
    if crit_abs and hll >= crit_abs:
        sev = CRITICAL
    elif median and median > 0 and hll >= median * ratio and hll >= min_abs:
        sev = WARNING
    if sev is None:
        return []

    ratio_note = f" (7d median {int(median):,} 대비 {hll / median:.1f}배)" if median else ""
    return [
        _finding(
            "innodb",
            "history_list_length",
            sev,
            round(hll),
            round(median) if median else None,
            f"InnoDB History List Length 가 {int(hll):,} 입니다{ratio_note}. "
            f"미purge undo 누적 — Long Transaction 또는 purge 지연 가능성이 있습니다 "
            f"(이 지표만으로 원인을 단정하지 말 것).",
            **_baseline_fields(ctx, "innodb_history_list_length", hll),
        )
    ]


def rule_lock_waiting_trx(ctx: Dict[str, Any], th: Dict[str, Any]) -> List[Dict[str, Any]]:
    """락 대기 중인 트랜잭션 수 탐지. (PRD 섹션 19)"""
    waiting = ctx["values"].get("innodb_trx_lock_waiting")
    if waiting is None or waiting < th.get("lock_wait", {}).get("warning", 1):
        return []
    return [
        _finding(
            "lock",
            "innodb_trx_lock_waiting",
            WARNING,
            waiting,
            0,
            f"락을 기다리는 트랜잭션이 {waiting:.0f}건 있습니다. 경합 대상 트랜잭션 확인이 필요합니다.",
        )
    ]


ALL_RULES = [
    rule_connection_usage,
    rule_threads_running_spike,
    rule_tmp_disk_ratio,
    rule_buffer_pool_hit,
    rule_dirty_page_ratio,
    rule_slow_query_rate,
    rule_lock_wait,
    rule_sql_rows_examined,
    rule_sql_latency_spike,
    rule_long_transaction,
    rule_lock_waiting_trx,
    rule_history_list_length,
    rule_replication,
]
