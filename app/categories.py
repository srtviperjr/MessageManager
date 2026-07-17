"""Persist business/personal categories for message threads."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal, Optional

from app.paths import data_dir

Category = Literal["business", "personal", "uncategorized"]

DATA_DIR = data_dir()
CATEGORIES_DB = DATA_DIR / "categories.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CATEGORIES_DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS thread_categories (
          chat_id INTEGER PRIMARY KEY,
          chat_guid TEXT,
          category TEXT NOT NULL CHECK (category IN ('business', 'personal')),
          notes TEXT,
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
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
    category: Category,
    chat_guid: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    if category == "uncategorized":
        clear_category(chat_id)
        return {
            "chat_id": chat_id,
            "chat_guid": chat_guid,
            "category": "uncategorized",
            "notes": notes,
            "updated_at": None,
        }

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
