"""Transaction / Lock 수집. (PRD 섹션 14)

information_schema.innodb_trx 로부터 요약 지표를 GAUGE metric 으로 만든다.
Raw SQL(trx_query)은 민감정보 우려로 저장하지 않는다. (PRD 섹션 30)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

QUERIES_DIR = Path(__file__).resolve().parent.parent.parent / "queries" / "mysql"

# innodb_trx 요약 컬럼 → metric 이름
_TRX_METRICS = [
    ("innodb_trx_count", "trx_count"),
    ("innodb_trx_running", "trx_running"),
    ("innodb_trx_lock_waiting", "trx_lock_waiting"),
    ("innodb_trx_longest_seconds", "longest_trx_seconds"),
]


def _load_query(name: str) -> str:
    return (QUERIES_DIR / name).read_text(encoding="utf-8")


def collect_transaction_metrics(conn) -> List[Tuple[str, str, float]]:
    """(name, 'GAUGE', value) 리스트 반환. 실패 시 빈 리스트."""
    sql = _load_query("transaction.sql")
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()  # DictCursor: 한 행
    except Exception as exc:  # noqa: BLE001 - 권한/버전 차이 흡수 (PRD 섹션 28)
        logger.warning("Transaction 수집 실패 (PROCESS 권한/innodb_trx 확인): %s", exc)
        return []

    if not row:
        return []

    results: List[Tuple[str, str, float]] = []
    for metric_name, col in _TRX_METRICS:
        value = row.get(col)
        if value is None:
            continue
        try:
            results.append((metric_name, "GAUGE", float(value)))
        except (TypeError, ValueError):
            continue

    logger.info("Collected %d transaction metrics", len(results))
    return results


def collect_history_list_length(conn) -> Optional[Tuple[str, str, float]]:
    """InnoDB History List Length 수집. (개선요청 §16) 실패 시 None."""
    # 1) 표준: information_schema.INNODB_METRICS
    try:
        with conn.cursor() as cur:
            cur.execute(_load_query("history_list.sql"))
            row = cur.fetchone()
            if row and row.get("hll") is not None:
                return ("innodb_history_list_length", "GAUGE", float(row["hll"]))
    except Exception as exc:  # noqa: BLE001
        logger.debug("INNODB_METRICS HLL 실패, INNODB STATUS 파싱 시도: %s", exc)

    # 2) 폴백: SHOW ENGINE INNODB STATUS 파싱
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW ENGINE INNODB STATUS")
            row = cur.fetchone()
            status = row.get("Status") if row else None
            if status:
                m = re.search(r"History list length\s+(\d+)", status)
                if m:
                    return ("innodb_history_list_length", "GAUGE", float(m.group(1)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("History List Length 수집 실패: %s", exc)
    return None
