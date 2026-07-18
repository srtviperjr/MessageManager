"""Versioned data migrations run on launch / after upgrades.

Policy (non-negotiable):
  Conversation categories are the most important user data.
  Migrations must copy/transform them — never delete the categories DB,
  never replace it with an empty file, and never drop rows except when
  converting explicit "uncategorized" placeholders (absence = uncategorized).

Before each schema step we snapshot categories.db under data/backups/.
After migrations we verify the row count did not shrink unexpectedly.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Optional

from app.logging_util import get_logger
from app.paths import data_dir
from app.version import APP_VERSION

log = get_logger("messagemanager.migrations")

# Bump when on-disk data format needs a transform.
CURRENT_SCHEMA_VERSION = 4

STATE_NAME = "install_state.json"


def _state_path() -> Path:
    return data_dir() / STATE_NAME


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"schema_version": 0, "last_app_version": None, "category_row_count": 0}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 0, "last_app_version": None, "category_row_count": 0}
    if not isinstance(raw, dict):
        return {"schema_version": 0, "last_app_version": None, "category_row_count": 0}
    try:
        schema = int(raw.get("schema_version", 0))
    except (TypeError, ValueError):
        schema = 0
    try:
        cat_count = int(raw.get("category_row_count") or 0)
    except (TypeError, ValueError):
        cat_count = 0
    return {
        "schema_version": max(0, schema),
        "last_app_version": raw.get("last_app_version"),
        "category_row_count": max(0, cat_count),
    }


def _save_state(state: dict[str, Any]) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _category_count() -> int:
    from app.categories import count_rows

    return count_rows()


def _backup_categories(reason: str) -> Optional[Path]:
    from app.categories import backup_categories_db

    path = backup_categories_db(reason)
    if path:
        log.info("Backed up categories DB -> %s", path)
    return path


def _restore_latest_backup() -> bool:
    from app.categories import latest_backup, restore_from_backup

    backup = latest_backup()
    if not backup:
        return False
    restored = restore_from_backup(backup)
    log.warning("Restored categories from %s (%s rows)", backup, restored)
    return True


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
    from app.categories import _migrate_schema, categories_db_path

    # Reading + writing forces the current normalizer.
    current = settings_store.get_settings()
    settings_store.update_settings(current)

    # Drop obsolete CHECK constraints if an older DB still has them.
    db = categories_db_path()
    if db.exists():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='thread_categories'"
            ).fetchone()
            sql = (row["sql"] if row else "") or ""
            if "CHECK (category IN" in sql:
                _migrate_schema(conn)
        finally:
            conn.close()


def _migrate_to_4() -> None:
    """Category durability: guid index, backup, and row-count bookkeeping."""
    from app.categories import _connect, backup_categories_db, count_rows

    backup_categories_db("migrate-v4")
    conn = _connect()
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_thread_categories_guid "
            "ON thread_categories(chat_guid)"
        )
        conn.commit()
    finally:
        conn.close()
    log.info("Category durability migration complete (%s rows)", count_rows())


MIGRATIONS: dict[int, Callable[[], None]] = {
    1: _migrate_to_1,
    2: _migrate_to_2,
    3: _migrate_to_3,
    4: _migrate_to_4,
}


def run_migrations() -> dict[str, Any]:
    """Apply pending migrations. Safe to call on every launch."""
    data_dir().mkdir(parents=True, exist_ok=True)
    state = _load_state()
    started = int(state.get("schema_version") or 0)
    previous_app = state.get("last_app_version")
    previous_count = int(state.get("category_row_count") or 0)
    count_before = _category_count()
    # Prefer the higher watermark so a partial write can't hide prior data.
    baseline = max(previous_count, count_before)

    if started < CURRENT_SCHEMA_VERSION and count_before > 0:
        _backup_categories(f"pre-upgrade-{previous_app or 'unknown'}-to-{APP_VERSION}")

    while started < CURRENT_SCHEMA_VERSION:
        nxt = started + 1
        fn = MIGRATIONS.get(nxt)
        if not fn:
            log.error("Missing migration for schema version %s", nxt)
            break
        log.info(
            "Running migration v%s (app %s -> %s, categories=%s)",
            nxt,
            previous_app or "unknown",
            APP_VERSION,
            _category_count(),
        )
        _backup_categories(f"pre-schema-v{nxt}")
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("Migration v%s failed — attempting category restore", nxt)
            _restore_latest_backup()
            raise
        after_step = _category_count()
        if baseline > 0 and after_step < baseline:
            log.error(
                "Category count dropped during migration v%s (%s -> %s); restoring backup",
                nxt,
                baseline,
                after_step,
            )
            if _restore_latest_backup():
                after_step = _category_count()
            if after_step < baseline:
                raise RuntimeError(
                    f"Category data loss detected during migration v{nxt} "
                    f"({baseline} -> {after_step})"
                )
        started = nxt
        state["schema_version"] = started
        state["category_row_count"] = after_step
        _save_state(state)

    final_count = _category_count()
    if baseline > 0 and final_count < baseline:
        log.error(
            "Category count dropped after migrations (%s -> %s); restoring backup",
            baseline,
            final_count,
        )
        if _restore_latest_backup():
            final_count = _category_count()
        if final_count < baseline:
            raise RuntimeError(
                f"Category data loss detected after upgrade ({baseline} -> {final_count})"
            )

    # On every launch (even when schema is current), keep a rotating backup when
    # the user has categories — cheap insurance against future bugs.
    if final_count > 0 and previous_app not in (None, APP_VERSION):
        _backup_categories(f"post-upgrade-{APP_VERSION}")

    state["schema_version"] = CURRENT_SCHEMA_VERSION
    state["last_app_version"] = APP_VERSION
    state["category_row_count"] = final_count
    _save_state(state)
    log.info(
        "Migrations ready schema=%s categories=%s previous_app=%s",
        CURRENT_SCHEMA_VERSION,
        final_count,
        previous_app,
    )
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "last_app_version": previous_app,
        "app_version": APP_VERSION,
        "upgraded": previous_app not in (None, APP_VERSION),
        "category_row_count": final_count,
        "category_rows_before": count_before,
    }
