"""Shared filesystem paths for local data."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("THREAD_LEDGER_DATA")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / "data"
