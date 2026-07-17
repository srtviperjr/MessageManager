"""Application file logging under Application Support or local data/."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.paths import data_dir

_configured = False


def log_dir() -> Path:
    # Prefer sibling logs/ next to data when THREAD_LEDGER_DATA is set
    # (packaged app uses ~/Library/Application Support/MessageManager/data).
    base = data_dir()
    if base.name == "data":
        return base.parent / "logs"
    return base / "logs"


def log_file_path() -> Path:
    return log_dir() / "app.log"


def configure_logging() -> Path:
    global _configured
    path = log_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if _configured:
        return path

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        path,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    _configured = True
    logging.getLogger(__name__).info("Logging to %s", path)
    return path


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
