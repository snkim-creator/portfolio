"""MySQL/MariaDB 접속 및 서버 기본정보 수집."""

from __future__ import annotations

import logging
from typing import Any, Dict

import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger(__name__)


def connect(db_cfg: Dict[str, Any]) -> pymysql.connections.Connection:
    """설정 dict 로 DB 에 접속한다. (DictCursor 사용)"""
    conn = pymysql.connect(
        host=db_cfg["host"],
        port=int(db_cfg.get("port", 3306)),
        user=db_cfg["user"],
        password=db_cfg["password"],
        database=db_cfg.get("database") or None,
        charset=db_cfg.get("charset", "utf8mb4"),
        connect_timeout=int(db_cfg.get("connect_timeout", 10)),
        cursorclass=DictCursor,
        autocommit=True,
    )
    logger.info("Connected to %s:%s", db_cfg["host"], db_cfg.get("port", 3306))
    return conn


def _scalar(conn, sql: str) -> Any:
    """단일 값을 반환하는 쿼리. 실패 시 None 반환(비정상 종료 방지)."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if not row:
                return None
            # DictCursor: 첫 컬럼 값
            return next(iter(row.values()))
    except Exception as exc:  # noqa: BLE001 - 서버 호환성 차이 흡수
        logger.warning("Query failed (%s): %s", sql, exc)
        return None


def get_server_info(conn) -> Dict[str, Any]:
    """서버 기본정보를 수집한다. MySQL/MariaDB 차이를 흡수한다."""
    version = _scalar(conn, "SELECT VERSION()")
    version_str = str(version) if version is not None else ""
    flavor = "MariaDB" if "mariadb" in version_str.lower() else "MySQL"

    info: Dict[str, Any] = {
        "version": version_str,
        "flavor": flavor,
        "hostname": _scalar(conn, "SELECT @@hostname"),
        "port": _scalar(conn, "SELECT @@port"),
        # MariaDB 10.x 에는 server_uuid 가 없을 수 있으므로 실패 허용
        "server_uuid": _scalar(conn, "SELECT @@server_uuid"),
        # Uptime 은 변수(@@uptime)가 아니라 상태변수라서 Global Status 에서 읽는다
        "uptime": _global_status_value(conn, "Uptime"),
        "max_connections": _scalar(conn, "SELECT @@max_connections"),
        "innodb_buffer_pool_size": _scalar(conn, "SELECT @@innodb_buffer_pool_size"),
    }

    # server_id: uuid 우선, 없으면 host:port 로 대체
    server_id = info["server_uuid"]
    if not server_id:
        server_id = f"{info['hostname']}:{info['port']}"
    info["server_id"] = str(server_id)

    logger.info("DB Version: %s %s", flavor, version_str)
    return info


def _global_status_value(conn, name: str) -> Any:
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW GLOBAL STATUS LIKE %s", (name,))
            row = cur.fetchone()
            if row:
                return row.get("Value")
    except Exception as exc:  # noqa: BLE001
        logger.warning("SHOW GLOBAL STATUS LIKE %s failed: %s", name, exc)
    return None
