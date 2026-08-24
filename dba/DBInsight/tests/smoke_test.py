"""DB 없이 실행 가능한 스모크 테스트: 스키마 생성 + 저장 로직 검증."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.storage import repository as r  # noqa: E402
from app.storage import sqlite as s  # noqa: E402

DB = "data/_smoketest.db"


def main() -> None:
    if os.path.exists(DB):
        os.remove(DB)
    conn = s.init_db(DB)
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    print("tables:", tables)

    sid = r.create_snapshot(
        conn,
        {
            "server_id": "uuid-1",
            "version": "8.0.36",
            "flavor": "MySQL",
            "hostname": "h1",
            "uptime": "12345",
        },
    )
    r.save_metrics(
        conn,
        sid,
        [("Threads_connected", "GAUGE", 42.0), ("Queries", "COUNTER", 1000000.0)],
    )
    r.save_sql_digests(
        conn,
        sid,
        [
            {
                "SCHEMA_NAME": "app",
                "DIGEST": "abc",
                "DIGEST_TEXT": "SELECT ?",
                "COUNT_STAR": 10,
                "SUM_TIMER_WAIT": 123,
                "AVG_TIMER_WAIT": 12,
                "MIN_TIMER_WAIT": 1,
                "MAX_TIMER_WAIT": 50,
                "SUM_ROWS_EXAMINED": 100,
                "SUM_ROWS_SENT": 10,
                "SUM_ROWS_AFFECTED": 0,
                "SUM_CREATED_TMP_TABLES": 0,
                "SUM_CREATED_TMP_DISK_TABLES": 0,
                "SUM_SELECT_SCAN": 1,
                "SUM_SELECT_FULL_JOIN": 0,
                "SUM_NO_INDEX_USED": 0,
                "SUM_NO_GOOD_INDEX_USED": 0,
                "FIRST_SEEN": "2026-08-18",
                "LAST_SEEN": "2026-08-18",
            }
        ],
    )

    assert tables == [
        "findings",
        "metrics",
        "reports",
        "snapshots",
        "sql_digest_metrics",
        "table_io_metrics",
    ], tables
    assert conn.execute("select count(*) from metrics").fetchone()[0] == 2
    assert conn.execute("select count(*) from sql_digest_metrics").fetchone()[0] == 1
    print("snapshot_id:", sid)
    conn.close()
    os.remove(DB)
    print("SMOKE OK")


if __name__ == "__main__":
    main()
