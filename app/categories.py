"""Persist categories for message conversations."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Optional

from app.paths import data_dir

BUILTIN_CATEGORIES = ("business", "personal", "uncategorized", "ignore")
# Kept for older imports / defaults.
ALL_CATEGORIES = BUILTIN_CATEGORIES

_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

DATA_DIR = data_dir()
CATEGORIES_DB = DATA_DIR / "categories.db"


def slugify_category(label: str) -> str:
    raw = (label or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw:
        raw = "custom"
    if raw[0].isdigit():
        raw = f"c_{raw}"
    return raw[:40]


def is_valid_category_id(category: str) -> bool:
    return bool(category and _CATEGORY_RE.match(category))


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Allow arbitrary category ids (custom categories) by dropping fixed CHECKs."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='thread_categories'"
    ).fetchone()
    if not row:
        return
    sql = (row["sql"] or "")
    if "CHECK (category IN" not in sql:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS thread_categories_new (
          chat_id INTEGER PRIMARY KEY,
          chat_guid TEXT,
          category TEXT NOT NULL,
          notes TEXT,
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO thread_categories_new
          (chat_id, chat_guid, category, notes, updated_at)
        SELECT chat_id, chat_guid, category, notes, updated_at
        FROM thread_categories
        WHERE category IS NOT NULL AND TRIM(category) != '' AND category != 'uncategorized'
        """
    )
    conn.execute("DROP TABLE thread_categories")
    conn.execute("ALTER TABLE thread_categories_new RENAME TO thread_categories")
    conn.commit()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CATEGORIES_DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS thread_categories (
          chat_id INTEGER PRIMARY KEY,
          chat_guid TEXT,
          category TEXT NOT NULL,
          notes TEXT,
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    _migrate_schema(conn)
    return conn


def get_all() -> dict[int, dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT chat_id, chat_guid, category, notes, updated_at FROM thread_categories"
        ).fetchall()
        return {
            int(row["chat_id"]): {
                "chat_id": row["chat_id"],
                "chat_guid": row["chat_guid"],
                "category": row["category"],
                "notes": row["notes"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }
    finally:
        conn.close()


def get_one(chat_id: int) -> Optional[dict[str, Any]]:
    return get_all().get(chat_id)


def set_category(
    chat_id: int,
    category: str,
    chat_guid: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    category = (category or "").strip().lower()
    if category == "uncategorized":
        clear_category(chat_id)
        return {
            "chat_id": chat_id,
            "chat_guid": chat_guid,
            "category": "uncategorized",
            "notes": notes,
            "updated_at": None,
        }

    if not is_valid_category_id(category):
        raise ValueError(f"Unsupported category: {category}")

    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO thread_categories (chat_id, chat_guid, category, notes, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(chat_id) DO UPDATE SET
              chat_guid = COALESCE(excluded.chat_guid, thread_categories.chat_guid),
              category = excluded.category,
              notes = COALESCE(excluded.notes, thread_categories.notes),
              updated_at = datetime('now')
            """,
            (chat_id, chat_guid, category, notes),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT chat_id, chat_guid, category, notes, updated_at
            FROM thread_categories WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def clear_category(chat_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM thread_categories WHERE chat_id = ?", (chat_id,))
        conn.commit()
    finally:
        conn.close()
