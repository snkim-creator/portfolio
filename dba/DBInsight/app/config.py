"""설정 로딩. config.yaml + .env 를 읽어 하나의 dict 로 제공한다."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

# 프로젝트 루트 (app/config.py -> app -> 루트)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


class ConfigError(Exception):
    """설정 관련 오류."""


def _resolve_path(value: str) -> Path:
    """상대경로는 프로젝트 루트 기준으로 절대경로화한다."""
    p = Path(value)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def load_config(config_path: str | os.PathLike | None = None) -> Dict[str, Any]:
    """config.yaml 과 .env 를 읽어 설정 dict 를 반환한다.

    다중 서버(Prometheus 스타일):
      - `servers`: 수집 대상 목록. 각 항목은 `defaults` 를 상속하며 개별 override 가능.
      - 각 서버의 비밀번호는 password_env 가 가리키는 환경변수에서 읽어 채운다.
    반환 dict 에는 정규화된 `servers` 리스트(각 항목에 name/endpoint/password 포함)가 담긴다.
    (구버전 단일 `database` 블록도 하위호환으로 지원)
    """
    load_dotenv(PROJECT_ROOT / ".env")

    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"설정 파일을 찾을 수 없습니다: {path}\n"
            f"config/config.example.yaml 을 복사해 config/config.yaml 을 만드세요."
        )

    with path.open("r", encoding="utf-8") as f:
        cfg: Dict[str, Any] = yaml.safe_load(f) or {}

    cfg["servers"] = _build_servers(cfg)
    _normalize_paths(cfg)
    return cfg


def _build_servers(cfg: Dict[str, Any]) -> list:
    """defaults + servers(또는 구버전 database) 를 정규화된 서버 리스트로 만든다."""
    defaults = cfg.get("defaults") or {}
    raw_servers = cfg.get("servers")

    if raw_servers is None:
        # 하위호환: 단일 database 블록
        db = cfg.get("database")
        if not isinstance(db, dict):
            raise ConfigError("config 에 servers(목록) 또는 database(단일) 섹션이 필요합니다.")
        raw_servers = [db]

    if not isinstance(raw_servers, list) or not raw_servers:
        raise ConfigError("servers 는 비어있지 않은 목록이어야 합니다.")

    seen_endpoints = set()
    servers = []
    for entry in raw_servers:
        if not isinstance(entry, dict):
            raise ConfigError("servers 의 각 항목은 매핑(host: ...)이어야 합니다.")
        merged = {**defaults, **entry}

        host = merged.get("host")
        if not host:
            raise ConfigError("각 서버 항목에 host 가 필요합니다.")
        merged["port"] = int(merged.get("port", 3306))

        env_name = merged.get("password_env")
        if not env_name:
            raise ConfigError(f"서버 {host} 에 password_env 가 필요합니다.")
        password = os.getenv(env_name)
        if password is None:
            raise ConfigError(
                f"환경변수 {env_name} 가 설정되어 있지 않습니다 (서버 {host}). "
                f".env 를 확인하세요."
            )
        merged["password"] = password

        merged["endpoint"] = f"{host}:{merged['port']}"
        merged["name"] = merged.get("name") or merged["endpoint"]

        if merged["endpoint"] in seen_endpoints:
            raise ConfigError(f"중복된 서버 endpoint: {merged['endpoint']}")
        seen_endpoints.add(merged["endpoint"])
        servers.append(merged)

    return servers


def _normalize_paths(cfg: Dict[str, Any]) -> None:
    storage = cfg.setdefault("storage", {})
    storage["db_path"] = str(
        _resolve_path(storage.get("db_path", "./data/dbinsight.db"))
    )

    report = cfg.setdefault("report", {})
    report["output_directory"] = str(
        _resolve_path(report.get("output_directory", "./reports"))
    )

    logging_cfg = cfg.setdefault("logging", {})
    logging_cfg["file"] = str(_resolve_path(logging_cfg.get("file", "./logs/app.log")))
