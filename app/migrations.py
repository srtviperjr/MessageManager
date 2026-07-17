"""Versioned data migrations run on launch / after upgrades."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from app.logging_util import get_logger
from app.paths import data_dir
from app.version import APP_VERSION

log = get_logger("messagemanager.migrations")

# Bump when on-disk data format needs a transform.
CURRENT_SCHEMA_VERSION = 3

STATE_NAME = "install_state.json"


def _state_path() -> Path:
    return data_dir() / STATE_NAME


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"schema_version": 0, "last_app_version": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 0, "last_app_version": None}
    if not isinstance(raw, dict):
        return {"schema_version": 0, "last_app_version": None}
    try:
        schema = int(raw.get("schema_version", 0))
    except (TypeError, ValueError):
        schema = 0
    return {
        "schema_version": max(0, schema),
        "last_app_version": raw.get("last_app_version"),
    }


def _save_state(state: dict[str, Any]) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _migrate_to_1() -> None:
    """Ensure categories DB exists with a usable table."""
    from app.categories import _connect

    conn = _connect()
    conn.close()


def _migrate_to_2() -> None:
    """Ensure ignore / flexible category storage is available."""
    from app.categories import _connect

    conn = _connect()
    conn.close()


def _migrate_to_3() -> None:
    """Normalize settings for 1.0 (custom categories, load modes, etc.)."""
    from app import settings as settings_store

    # Reading + writing forces the current normalizer.
    current = settings_store.get_settings()
    settings_store.update_settings(current)

    # Drop obsolete CHECK constraints if an older DB still has them.
    db = data_dir() / "categories.db"
    if db.exists():
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='thread_categories'"
            ).fetchone()
            sql = (row[0] if row else "") or ""
            if "CHECK (category IN" in sql:
                from app.categories import _migrate_schema

                _migrate_schema(conn)
        finally:
            conn.close()


MIGRATIONS: dict[int, Callable[[], None]] = {
    1: _migrate_to_1,
    2: _migrate_to_2,
    3: _migrate_to_3,
}


def run_migrations() -> dict[str, Any]:
    """Apply pending migrations. Safe to call on every launch."""
    data_dir().mkdir(parents=True, exist_ok=True)
    state = _load_state()
    started = int(state.get("schema_version") or 0)
    previous_app = state.get("last_app_version")

    while started < CURRENT_SCHEMA_VERSION:
        nxt = started + 1
        fn = MIGRATIONS.get(nxt)
        if not fn:
            log.error("Missing migration for schema version %s", nxt)
            break
        log.info(
            "Running migration v%s (app %s -> %s)",
            nxt,
            previous_app or "unknown",
            APP_VERSION,
        )
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("Migration v%s failed", nxt)
            raise
        started = nxt
        state["schema_version"] = started
        _save_state(state)

    state["schema_version"] = CURRENT_SCHEMA_VERSION
    state["last_app_version"] = APP_VERSION
    _save_state(state)
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "last_app_version": previous_app,
        "app_version": APP_VERSION,
        "upgraded": previous_app not in (None, APP_VERSION),
    }
