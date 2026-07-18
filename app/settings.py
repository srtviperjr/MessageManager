"""Persist app settings (including Apple Intelligence toggle)."""

from __future__ import annotations

import json
from typing import Any

from app.categories import BUILTIN_CATEGORIES, is_valid_category_id, slugify_category
from app.paths import data_dir
from app.platform_info import is_apple_silicon

DATA_DIR = data_dir()
SETTINGS_PATH = DATA_DIR / "settings.json"

# Backward-compatible alias used elsewhere.
ALL_CATEGORIES = BUILTIN_CATEGORIES


def default_settings() -> dict[str, Any]:
    # Apple Silicon defaults to AI summaries; Intel stays on extractive.
    return {
        "apple_intelligence_enabled": is_apple_silicon(),
        "apple_intelligence_shortcut": "MessageManager Summarize",
        "summary_days": 30,
        "thread_limit": 50,
        "thread_load_mode": "count",  # count | activity
        "thread_activity_value": 6,
        "thread_activity_unit": "months",  # months | years
        "auto_load_on_start": False,
        "default_message_limit": 10,
        # python | terminal — how to re-copy Messages into the local cache
        "cache_sync_method": "python",
        "custom_categories": [],
        "enabled_categories": list(BUILTIN_CATEGORIES),
        "hidden_from_default": ["ignore"],
    }


def _normalize_custom_categories(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str):
            label = item.strip()
            cat_id = slugify_category(label)
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("id") or "").strip()
            cat_id = str(item.get("id") or "").strip().lower() or slugify_category(label)
        else:
            continue
        if not label or not is_valid_category_id(cat_id):
            continue
        if cat_id in BUILTIN_CATEGORIES or cat_id in seen:
            continue
        seen.add(cat_id)
        out.append({"id": cat_id, "label": label[:60]})
    return out


def _known_category_ids(settings: dict[str, Any]) -> set[str]:
    custom = {c["id"] for c in settings.get("custom_categories") or []}
    return set(BUILTIN_CATEGORIES) | custom


def _normalize_category_list(
    value: Any,
    *,
    known: set[str],
    fallback: list[str],
) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    out: list[str] = []
    for item in value:
        key = str(item).strip().lower()
        if key in known and key not in out:
            out.append(key)
    return out or list(fallback)


def activity_value_to_days(value: int, unit: str) -> int:
    unit = (unit or "months").lower()
    value = max(1, min(int(value), 100))
    if unit == "years":
        return value * 365
    return value * 30


def _normalize(settings: dict[str, Any]) -> dict[str, Any]:
    defaults = default_settings()
    merged = dict(defaults)
    merged.update({k: v for k, v in settings.items() if k in defaults})

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

    mode = str(merged.get("thread_load_mode") or "count").lower()
    merged["thread_load_mode"] = mode if mode in {"count", "activity"} else "count"

    try:
        activity_value = int(merged.get("thread_activity_value", 6))
    except (TypeError, ValueError):
        activity_value = 6
    merged["thread_activity_value"] = max(1, min(activity_value, 100))

    unit = str(merged.get("thread_activity_unit") or "months").lower()
    merged["thread_activity_unit"] = unit if unit in {"months", "years"} else "months"

    merged["auto_load_on_start"] = bool(merged.get("auto_load_on_start", False))

    try:
        msg_limit = int(merged.get("default_message_limit", 10))
    except (TypeError, ValueError):
        msg_limit = 10
    merged["default_message_limit"] = max(1, min(msg_limit, 500))

    sync_method = str(merged.get("cache_sync_method") or "python").lower()
    # Legacy "app" (MessageManager.app sync) removed — migrate to python.
    if sync_method == "app":
        sync_method = "python"
    merged["cache_sync_method"] = (
        sync_method if sync_method in {"python", "terminal"} else "python"
    )

    shortcut = str(merged.get("apple_intelligence_shortcut") or "").strip()
    merged["apple_intelligence_shortcut"] = shortcut or "MessageManager Summarize"

    merged["custom_categories"] = _normalize_custom_categories(
        merged.get("custom_categories")
    )
    known = _known_category_ids(merged)

    enabled = _normalize_category_list(
        merged.get("enabled_categories"),
        known=known,
        fallback=list(BUILTIN_CATEGORIES),
    )
    if "uncategorized" not in enabled:
        enabled.insert(0, "uncategorized")
    merged["enabled_categories"] = enabled

    hidden = _normalize_category_list(
        merged.get("hidden_from_default"),
        known=known,
        fallback=["ignore"],
    )
    merged["hidden_from_default"] = [c for c in hidden if c in enabled]
    return merged


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
    if not isinstance(raw, dict):
        return dict(defaults)
    return _normalize(raw)


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    defaults = default_settings()
    current = get_settings()
    for key, value in patch.items():
        if key not in defaults:
            continue
        current[key] = value
    current = _normalize(current)
    _ensure()
    SETTINGS_PATH.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return current
