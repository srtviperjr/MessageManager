"""Persist categories for message conversations.

Category assignments are the most important user data in MessageManager.
They live under Application Support (packaged) or ./data (dev) and must
survive app upgrades. Schema changes must copy/transform rows — never wipe.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.paths import data_dir

BUILTIN_CATEGORIES = ("business", "personal", "uncategorized", "ignore")
# Kept for older imports / defaults.
ALL_CATEGORIES = BUILTIN_CATEGORIES

_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def categories_db_path() -> Path:
    """Resolve at call time so THREAD_LEDGER_DATA is honored after launch env setup."""
    return data_dir() / "categories.db"


def backups_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Backward-compatible names (resolved lazily via properties would be nicer,
# but existing imports expect Path-like usage in a few places).
DATA_DIR = data_dir()
CATEGORIES_DB = categories_db_path()


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


def backup_categories_db(reason: str = "manual") -> Optional[Path]:
    """Copy categories.db before any destructive/transforming change.

    Returns the backup path, or None if there is nothing to back up yet.
    """
    src = categories_db_path()
    if not src.exists() or src.stat().st_size == 0:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_reason = re.sub(r"[^a-zA-Z0-9._-]+", "-", reason).strip("-")[:48] or "backup"
    dest = backups_dir() / f"categories-{stamp}-{safe_reason}.db"
    shutil.copy2(src, dest)
    _prune_backups(keep=20)
    return dest


def _prune_backups(keep: int = 20) -> None:
    files = sorted(backups_dir().glob("categories-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def count_rows(conn: Optional[sqlite3.Connection] = None) -> int:
    own = conn is None
    if own:
        path = categories_db_path()
        if not path.exists():
            return 0
        conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='thread_categories'"
        ).fetchone()
        if not row or not row[0]:
            return 0
        return int(conn.execute("SELECT COUNT(*) FROM thread_categories").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        if own:
            conn.close()


def latest_backup() -> Optional[Path]:
    files = sorted(backups_dir().glob("categories-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def restore_from_backup(backup: Path) -> int:
    """Replace categories.db from a backup. Returns restored row count."""
    if not backup.exists():
        raise FileNotFoundError(backup)
    dest = categories_db_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Keep a safety copy of whatever is being replaced.
    if dest.exists():
        backup_categories_db("pre-restore")
    shutil.copy2(backup, dest)
    return count_rows()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Allow arbitrary category ids (custom categories) by dropping fixed CHECKs.

    Never drops user rows: copies every assigned category into the new table,
    verifies counts, and only then swaps tables.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='thread_categories'"
    ).fetchone()
    if not row:
        return
    sql = (row["sql"] if isinstance(row, sqlite3.Row) else row[0]) or ""
    if "CHECK (category IN" not in sql:
        return

    before = count_rows(conn)
    backup_categories_db("pre-check-constraint-drop")

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            CREATE TABLE thread_categories_new (
              chat_id INTEGER PRIMARY KEY,
              chat_guid TEXT,
              category TEXT NOT NULL,
              notes TEXT,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Preserve every assigned category. "uncategorized" is represented by
        # absence of a row, so skip those if any legacy rows used that value.
        conn.execute(
            """
            INSERT INTO thread_categories_new
              (chat_id, chat_guid, category, notes, updated_at)
            SELECT chat_id, chat_guid, category, notes, updated_at
            FROM thread_categories
            WHERE category IS NOT NULL
              AND TRIM(category) != ''
              AND lower(category) != 'uncategorized'
            """
        )
        after = int(
            conn.execute("SELECT COUNT(*) FROM thread_categories_new").fetchone()[0]
        )
        # Allow equal or drop only of pure 'uncategorized' rows.
        legacy_uncat = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM thread_categories
                WHERE category IS NOT NULL AND lower(trim(category)) = 'uncategorized'
                """
            ).fetchone()[0]
        )
        if after < before - legacy_uncat:
            raise RuntimeError(
                f"Refusing schema migrate: would lose categories ({before} -> {after})"
            )
        conn.execute("DROP TABLE thread_categories")
        conn.execute("ALTER TABLE thread_categories_new RENAME TO thread_categories")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_thread_categories_guid "
            "ON thread_categories(chat_guid)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _connect() -> sqlite3.Connection:
    path = categories_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_thread_categories_guid "
        "ON thread_categories(chat_guid)"
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


def get_all_by_guid() -> dict[str, dict[str, Any]]:
    """Map chat_guid -> category row for recovery when Messages reassigns chat_id."""
    out: dict[str, dict[str, Any]] = {}
    for info in get_all().values():
        guid = (info.get("chat_guid") or "").strip()
        if guid:
            out[guid] = info
    return out


def get_one(chat_id: int) -> Optional[dict[str, Any]]:
    return get_all().get(chat_id)


def rebind_chat_id(old_chat_id: int, new_chat_id: int, chat_guid: Optional[str] = None) -> bool:
    """Move a category row onto a new Messages chat_id (same conversation)."""
    if old_chat_id == new_chat_id:
        return True
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT chat_id, chat_guid, category, notes FROM thread_categories WHERE chat_id = ?",
            (old_chat_id,),
        ).fetchone()
        if not row:
            return False
        existing = conn.execute(
            "SELECT chat_id FROM thread_categories WHERE chat_id = ?",
            (new_chat_id,),
        ).fetchone()
        if existing:
            # Prefer keeping an already-correct new id; drop the stale key.
            conn.execute("DELETE FROM thread_categories WHERE chat_id = ?", (old_chat_id,))
            conn.commit()
            return True
        conn.execute(
            """
            UPDATE thread_categories
            SET chat_id = ?,
                chat_guid = COALESCE(?, chat_guid),
                updated_at = datetime('now')
            WHERE chat_id = ?
            """,
            (new_chat_id, chat_guid, old_chat_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def resolve_for_thread(chat_id: int, chat_guid: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Find category by chat_id, else by chat_guid (and heal the stored chat_id)."""
    by_id = get_all()
    info = by_id.get(chat_id)
    if info:
        # Backfill guid if we learned it later.
        if chat_guid and not info.get("chat_guid"):
            set_category(chat_id, info["category"], chat_guid=chat_guid, notes=info.get("notes"))
            info = get_all().get(chat_id)
        return info

    guid = (chat_guid or "").strip()
    if not guid:
        return None
    for old_id, row in by_id.items():
        if (row.get("chat_guid") or "").strip() == guid:
            rebind_chat_id(old_id, chat_id, chat_guid=guid)
            return get_all().get(chat_id)
    return None


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


def status() -> dict[str, Any]:
    path = categories_db_path()
    return {
        "path": str(path),
        "exists": path.exists(),
        "row_count": count_rows(),
        "backup_count": len(list(backups_dir().glob("categories-*.db"))),
        "latest_backup": str(latest_backup()) if latest_backup() else None,
    }
