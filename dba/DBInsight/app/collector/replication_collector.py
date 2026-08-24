"""Replication 상태 수집. (복제 구성 서버)

- MariaDB: SHOW ALL SLAVES STATUS(다중소스) → SHOW SLAVE STATUS
- MySQL 8.0.22+: SHOW REPLICA STATUS
권한: MariaDB 10.5+ SLAVE MONITOR / MySQL REPLICATION CLIENT 필요. 없거나 복제 아님이면 빈 결과.

여러 채널(다중소스)이면 최악값으로 집계한다: 스레드는 모두 Yes 여야 정상, 지연은 최대값.
숫자 GAUGE 로만 저장(테이블 스키마 유지). Last_Error 원문은 리포트에서 "SHOW REPLICA STATUS 확인" 유도.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _g(row: dict, *names: str) -> Optional[Any]:
    for n in names:
        if n in row and row[n] is not None:
            return row[n]
    return None


def collect_replication_metrics(conn) -> List[Tuple[str, str, float]]:
    """복제 상태를 (name, 'GAUGE', value) 리스트로 반환. 복제 아님/권한없음 → []."""
    rows: List[dict] = []
    for stmt in ("SHOW ALL SLAVES STATUS", "SHOW REPLICA STATUS", "SHOW SLAVE STATUS"):
        try:
            with conn.cursor() as cur:
                cur.execute(stmt)
                rows = list(cur.fetchall())
            break
        except Exception as exc:  # noqa: BLE001 - 버전/권한 차이 흡수
            logger.debug("%s 실패: %s", stmt, exc)
            continue

    io_all, sql_all = 1.0, 1.0
    behind_max: Optional[float] = None
    errno = 0.0
    any_replica = False

    for row in rows:
        if not _g(row, "Master_Host", "Source_Host"):
            continue  # 복제 설정 안 된 행
        any_replica = True
        if str(_g(row, "Slave_IO_Running", "Replica_IO_Running") or "") != "Yes":
            io_all = 0.0
        if str(_g(row, "Slave_SQL_Running", "Replica_SQL_Running") or "") != "Yes":
            sql_all = 0.0
        b = _g(row, "Seconds_Behind_Master", "Seconds_Behind_Source")
        if b is not None:
            try:
                behind_max = max(behind_max or 0.0, float(b))
            except (TypeError, ValueError):
                pass
        e = _g(row, "Last_Errno", "Last_SQL_Errno")
        try:
            if e is not None and float(e) != 0:
                errno = float(e)
        except (TypeError, ValueError):
            pass

    if not any_replica:
        return []

    out: List[Tuple[str, str, float]] = [
        ("replica_is_replica", "GAUGE", 1.0),
        ("replica_io_running", "GAUGE", io_all),
        ("replica_sql_running", "GAUGE", sql_all),
        ("replica_last_errno", "GAUGE", errno),
    ]
    if behind_max is not None:  # 스레드 중단 시 NULL 일 수 있어 조건부 저장
        out.append(("replica_seconds_behind", "GAUGE", behind_max))

    logger.info(
        "Collected replication metrics (io=%.0f sql=%.0f behind=%s errno=%.0f)",
        io_all, sql_all, behind_max, errno,
    )
    return out
