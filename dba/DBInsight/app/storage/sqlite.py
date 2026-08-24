"""SQLite 초기화 및 스키마 생성. (PRD 섹션 24)"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id     TEXT,
    conn_endpoint TEXT,          -- 접속 대상 host:port (config 기준, 다중 서버 구분용)
    snapshot_time TEXT NOT NULL,
    db_version    TEXT,
    db_flavor     TEXT,
    hostname      TEXT,
    uptime        INTEGER,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS metrics (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    metric_name  TEXT NOT NULL,
    metric_type  TEXT,
    metric_value REAL
);
CREATE INDEX IF NOT EXISTS idx_metrics_snapshot ON metrics(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);

CREATE TABLE IF NOT EXISTS sql_digest_metrics (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id       INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    schema_name       TEXT,
    digest            TEXT,
    digest_text       TEXT,
    execution_count   INTEGER,
    total_latency     REAL,
    avg_latency       REAL,
    min_latency       REAL,
    max_latency       REAL,
    rows_examined     INTEGER,
    rows_sent         INTEGER,
    rows_affected     INTEGER,
    tmp_tables        INTEGER,
    tmp_disk_tables   INTEGER,
    select_scan       INTEGER,
    select_full_join  INTEGER,
    no_index_used     INTEGER,
    no_good_index_used INTEGER,
    first_seen        TEXT,
    last_seen         TEXT
);
CREATE INDEX IF NOT EXISTS idx_digest_snapshot ON sql_digest_metrics(snapshot_id);

CREATE TABLE IF NOT EXISTS table_io_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    object_schema   TEXT,
    object_name     TEXT,
    count_read      INTEGER,
    count_write     INTEGER,
    sum_timer_read  REAL,
    sum_timer_write REAL
);
CREATE INDEX IF NOT EXISTS idx_tableio_snapshot ON table_io_metrics(snapshot_id);

-- 이후 단계(Analyzer / AI Report)에서 사용할 테이블. Task 1 에서는 생성만 한다.
CREATE TABLE IF NOT EXISTS findings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id    INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    category       TEXT,
    severity       TEXT,
    metric         TEXT,
    finding_key    TEXT,     -- 날짜 간 동일 finding 매칭용 안정 키 (category:metric[:digest])
    current_value  REAL,
    baseline_value REAL,
    description    TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE CASCADE,
    report_date TEXT,
    report_path TEXT,
    ai_provider TEXT,
    ai_model    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    """DB 파일과 스키마를 준비하고 커넥션을 반환한다."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    logger.info("SQLite initialized at %s", path)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """기존 DB 에 없는 컬럼을 추가하는 경량 마이그레이션."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(snapshots)")]
    if "conn_endpoint" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN conn_endpoint TEXT")
        logger.info("Migration: snapshots.conn_endpoint 컬럼 추가")

    fcols = [row[1] for row in conn.execute("PRAGMA table_info(findings)")]
    if "finding_key" not in fcols:
        conn.execute("ALTER TABLE findings ADD COLUMN finding_key TEXT")
        logger.info("Migration: findings.finding_key 컬럼 추가")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_findings_key ON findings(finding_key)")
