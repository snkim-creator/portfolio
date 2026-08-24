"""로깅 설정. 콘솔 + 파일(logs/app.log) 동시 출력."""

from __future__ import annotations

import logging
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_file: str, level: str = "INFO") -> None:
    """루트 로거를 콘솔/파일 핸들러로 구성한다. (중복 호출 안전)"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, str(level).upper(), logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(log_level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    _CONFIGURED = True
