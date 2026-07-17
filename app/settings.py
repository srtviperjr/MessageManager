"""Persist app settings (including Apple Intelligence toggle)."""

from __future__ import annotations

import json
from typing import Any

from app.paths import data_dir
from app.platform_info import is_apple_silicon

DATA_DIR = data_dir()
SETTINGS_PATH = DATA_DIR / "settings.json"


def default_settings() -> dict[str, Any]:
    # Apple Silicon defaults to AI summaries; Intel stays on extractive.
    return {
        "apple_intelligence_enabled": is_apple_silicon(),
        "apple_intelligence_shortcut": "MessageManager Summarize",
        "summary_days": 30,
        "thread_limit": 50,
    }


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_settings() -> dict[str, Any]:
    _ensure()
    defaults = default_settings()
    if not SETTINGS_PATH.exists():
        return dict(defaults)
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(defaults)
    merged = dict(defaults)
    merged.update({k: v for k, v in raw.items() if k in defaults})
    # Intel can never actually use Apple Intelligence.
    if not is_apple_silicon():
        merged["apple_intelligence_enabled"] = False
    try:
        days = int(merged.get("summary_days", 30))
    except (TypeError, ValueError):
        days = 30
    merged["summary_days"] = max(1, min(days, 3650))
    try:
        thread_limit = int(merged.get("thread_limit", 50))
    except (TypeError, ValueError):
        thread_limit = 50
    merged["thread_limit"] = max(5, min(thread_limit, 100_000))
    return merged


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    defaults = default_settings()
    current = get_settings()
    for key, value in patch.items():
        if key not in defaults:
            continue
        current[key] = value
    if not is_apple_silicon():
        current["apple_intelligence_enabled"] = False
    try:
        days = int(current.get("summary_days", 30))
    except (TypeError, ValueError):
        days = 30
    current["summary_days"] = max(1, min(days, 3650))
    try:
        thread_limit = int(current.get("thread_limit", 50))
    except (TypeError, ValueError):
        thread_limit = 50
    current["thread_limit"] = max(5, min(thread_limit, 100_000))
    _ensure()
    SETTINGS_PATH.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return current
