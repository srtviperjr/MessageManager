"""Read-only access to the local macOS Messages database."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from app.contacts import (
    contacts_status,
    display_label,
    looks_like_handle,
    refresh_contacts,
    resolve_handle,
    resolve_handles,
)

ProgressFn = Callable[[str, int], None]

MESSAGES_DIR = Path.home() / "Library" / "Messages"
CHAT_DB = MESSAGES_DIR / "chat.db"

# Apple Core Data / Cocoa absolute time: nanoseconds since 2001-01-01 UTC
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


class MessagesAccessError(Exception):
    """Raised when chat.db cannot be read (usually Full Disk Access)."""


def apple_time_to_datetime(value: Optional[int]) -> Optional[datetime]:
    if value is None:
        return None
    # Older DBs used seconds; modern use nanoseconds.
    seconds = value / 1_000_000_000 if value > 1_000_000_000_000 else float(value)
    return APPLE_EPOCH + timedelta(seconds=seconds)


def datetime_to_apple_bounds(dt: datetime) -> tuple[int, int]:
    """Return (nanoseconds, seconds) Apple absolute-time cutoffs for SQL filters."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    seconds = (dt - APPLE_EPOCH).total_seconds()
    return int(seconds * 1_000_000_000), int(seconds)


def _messages_cache_dir() -> Optional[Path]:
    raw = (os.environ.get("THREAD_LEDGER_MESSAGES_CACHE") or "").strip()
    if not raw:
        # Packaged launcher default location.
        candidate = (
            Path.home()
            / "Library"
            / "Application Support"
            / "MessageManager"
            / "messages-cache"
        )
        if (candidate / "chat.db").is_file():
            return candidate
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def _copy_chat_db() -> Path:
    cache_dir = _messages_cache_dir()
    if cache_dir is not None:
        cached = cache_dir / "chat.db"
        if cached.is_file():
            # Native app launcher refreshes this cache while FDA applies to the app binary.
            temp_dir = Path(tempfile.mkdtemp(prefix="imessage-categorizer-"))
            for name in ("chat.db", "chat.db-wal", "chat.db-shm"):
                src = cache_dir / name
                if src.exists():
                    shutil.copy2(src, temp_dir / name)
            return temp_dir / "chat.db"

    if not CHAT_DB.exists():
        raise MessagesAccessError(
            f"Messages database not found at {CHAT_DB}. "
            "Open the Messages app once, then try again."
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="imessage-categorizer-"))
    try:
        for name in ("chat.db", "chat.db-wal", "chat.db-shm"):
            src = MESSAGES_DIR / name
            if src.exists():
                shutil.copy2(src, temp_dir / name)
    except PermissionError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise MessagesAccessError(
            "Permission denied reading Messages. Grant Full Disk Access, then quit and reopen."
        ) from exc
    except OSError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise MessagesAccessError(f"Could not copy Messages database: {exc}") from exc

    return temp_dir / "chat.db"


def connect_messages() -> tuple[sqlite3.Connection, Path]:
    """Return a connection to a temp copy of chat.db and the temp db path."""
    db_path = _copy_chat_db()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn, db_path


def cleanup_temp_db(db_path: Path) -> None:
    parent = db_path.parent
    if parent.name.startswith("imessage-categorizer-"):
        shutil.rmtree(parent, ignore_errors=True)


def _decode_attributed_body(blob: Optional[bytes]) -> Optional[str]:
    """Best-effort extract of plain text from attributedBody NSKeyedArchiver data."""
    if not blob:
        return None
    try:
        # Common pattern: UTF-8 / UTF-16 strings embedded in the archive.
        text = blob.decode("utf-8", errors="ignore")
        # Prefer the typedstream / NSString payload markers when present.
        match = re.search(r"NSString\x00.\x01.\x00+([^\x00]+)", text)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
        # Fallback: longest printable run
        runs = re.findall(r"[\x20-\x7E\u00A0-\uFFFF]{4,}", text)
        if runs:
            return max(runs, key=len).strip()
    except Exception:
        return None
    return None


def message_text(row: sqlite3.Row) -> str:
    text = row["text"] if "text" in row.keys() else None
    if text:
        return text
    body = row["attributedBody"] if "attributedBody" in row.keys() else None
    decoded = _decode_attributed_body(body)
    return decoded or ""


def _labeled_participants(participants: list[str]) -> list[str]:
    resolved = resolve_handles(participants)
    return [resolved.get(p, p) for p in participants]


def thread_display_name(row: sqlite3.Row, participants: list[str]) -> str:
    display = (row["display_name"] or "").strip()
    if display and not looks_like_handle(display):
        return display

    labels = _labeled_participants(participants)
    if labels:
        return ", ".join(labels[:4]) + ("…" if len(labels) > 4 else "")

    if display:
        return resolve_handle(display) or display

    ident = (row["chat_identifier"] or "").strip()
    if ident:
        return resolve_handle(ident) or ident
    return f"Chat {row['id']}"


def _report(progress: Optional[ProgressFn], message: str, percent: int) -> None:
    if progress:
        progress(message, max(0, min(100, int(percent))))


# Practical upper bound so a bad client can't request an unbounded load.
MAX_THREAD_LIMIT = 100_000


def count_threads() -> int:
    """Total conversations available in Messages."""
    conn, db_path = connect_messages()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM chat").fetchone()
        return int(row["n"] or 0)
    finally:
        conn.close()
        cleanup_temp_db(db_path)


def list_threads(
    limit: Optional[int] = 50,
    activity_days: Optional[int] = None,
    progress: Optional[ProgressFn] = None,
) -> tuple[list[dict[str, Any]], int]:
    """Lightweight thread index for recent conversations.

    Use ``limit`` for the N most recent threads, or ``activity_days`` to include
    every thread with activity in that window. Returns (threads, available_count).
    """
    use_activity = activity_days is not None and int(activity_days) > 0
    if use_activity:
        activity_days = max(1, min(int(activity_days), 36500))
        limit = MAX_THREAD_LIMIT
    else:
        limit = max(1, min(int(limit or 50), MAX_THREAD_LIMIT))

    _report(progress, "Copying Messages database…", 8)
    conn, db_path = connect_messages()
    try:
        available = int(conn.execute("SELECT COUNT(*) AS n FROM chat").fetchone()["n"] or 0)

        _report(progress, "Loading Contacts (timeout 6s)…", 18)
        refresh_contacts(timeout=6.0)
        status = contacts_status(quick=True)
        if status.get("error") and not status.get("contact_keys"):
            _report(
                progress,
                "Contacts unavailable — using phone numbers…",
                28,
            )
        elif status.get("error"):
            _report(progress, f"Contacts: {status['error']}", 28)
        else:
            _report(
                progress,
                f"Contacts ready ({status.get('contact_keys', 0)} matches)…",
                28,
            )

        params: list[Any] = []
        activity_sql = ""
        if use_activity:
            cutoff = datetime.now(timezone.utc) - timedelta(days=activity_days)
            cutoff_ns, cutoff_sec = datetime_to_apple_bounds(cutoff)
            activity_sql = """
              AND (
                (
                  SELECT MAX(cmj2.message_date)
                  FROM chat_message_join cmj2
                  WHERE cmj2.chat_id = c.ROWID
                ) >= ?
                OR (
                  (
                    SELECT MAX(cmj2.message_date)
                    FROM chat_message_join cmj2
                    WHERE cmj2.chat_id = c.ROWID
                  ) < 1000000000000
                  AND (
                    SELECT MAX(cmj2.message_date)
                    FROM chat_message_join cmj2
                    WHERE cmj2.chat_id = c.ROWID
                  ) >= ?
                )
              )
            """
            params.extend([cutoff_ns, cutoff_sec])
            _report(
                progress,
                f"Listing conversations active in the last {activity_days} days…",
                40,
            )
        else:
            if available > 0:
                limit = min(limit, available)
            _report(progress, f"Listing {limit} most recent conversations…", 40)

        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT
              c.ROWID AS id,
              c.guid AS guid,
              c.chat_identifier AS chat_identifier,
              c.display_name AS display_name,
              c.style AS style,
              (
                SELECT MAX(cmj.message_date)
                FROM chat_message_join cmj
                WHERE cmj.chat_id = c.ROWID
              ) AS last_date,
              (
                SELECT COUNT(*)
                FROM chat_message_join cmj
                WHERE cmj.chat_id = c.ROWID
              ) AS message_count
            FROM chat c
            WHERE 1=1
            {activity_sql}
            ORDER BY last_date DESC NULLS LAST
            LIMIT ?
            """,
            params,
        ).fetchall()

        chat_ids = [int(row["id"]) for row in rows]
        total = len(chat_ids)
        _report(progress, f"Found {total} conversations…", 55)

        participants_by_chat: dict[int, list[str]] = defaultdict(list)
        if chat_ids:
            _report(progress, "Loading participants…", 65)
            placeholders = ",".join("?" * len(chat_ids))
            for handle_row in conn.execute(
                f"""
                SELECT chj.chat_id AS chat_id, h.id AS handle
                FROM chat_handle_join chj
                JOIN handle h ON h.ROWID = chj.handle_id
                WHERE chj.chat_id IN ({placeholders})
                ORDER BY chj.chat_id, h.ROWID
                """,
                chat_ids,
            ):
                participants_by_chat[int(handle_row["chat_id"])].append(handle_row["handle"])

        all_handles = sorted({h for handles in participants_by_chat.values() for h in handles})
        _report(progress, "Resolving contact names…", 80)
        handle_names = resolve_handles(all_handles)

        threads: list[dict[str, Any]] = []
        for row in rows:
            participants = participants_by_chat.get(int(row["id"]), [])
            labeled = [handle_names.get(p, p) for p in participants]
            last_dt = apple_time_to_datetime(row["last_date"])
            threads.append(
                {
                    "id": row["id"],
                    "guid": row["guid"],
                    "chat_identifier": row["chat_identifier"],
                    "display_name": thread_display_name(row, participants),
                    "participants": participants,
                    "participant_names": labeled,
                    "is_group": bool(row["style"] and row["style"] != 45),
                    "message_count": row["message_count"] or 0,
                    "last_message_at": last_dt.isoformat() if last_dt else None,
                    # Previews are intentionally omitted — list shows last activity time only.
                    "preview": "",
                }
            )

        _report(progress, f"Loaded {len(threads)} conversations", 100)
        return threads, available
    finally:
        conn.close()
        cleanup_temp_db(db_path)


def get_thread_messages(
    chat_id: int,
    limit: int = 500,
    days: Optional[int] = None,
    progress: Optional[ProgressFn] = None,
) -> dict[str, Any]:
    """Load message bodies for one thread. Used for summarization, not the list."""
    _report(progress, "Copying Messages database…", 8)
    conn, db_path = connect_messages()
    try:
        _report(progress, "Loading Contacts (timeout 6s)…", 16)
        refresh_contacts(timeout=6.0)
        window = f"last {days} day{'s' if days != 1 else ''}" if days else "conversation"
        _report(progress, f"Reading messages ({window})…", 35)
        chat = conn.execute(
            """
            SELECT ROWID AS id, guid, chat_identifier, display_name, style
            FROM chat WHERE ROWID = ?
            """,
            (chat_id,),
        ).fetchone()
        if not chat:
            raise KeyError(f"Chat {chat_id} not found")

        participants = [
            r["id"]
            for r in conn.execute(
                """
                SELECT h.id
                FROM handle h
                JOIN chat_handle_join chj ON chj.handle_id = h.ROWID
                WHERE chj.chat_id = ?
                ORDER BY h.ROWID
                """,
                (chat_id,),
            ).fetchall()
        ]

        params: list[Any] = [chat_id]
        date_filter = ""
        cutoff_iso = None
        if days is not None and days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            cutoff_iso = cutoff.isoformat()
            cutoff_ns, cutoff_sec = datetime_to_apple_bounds(cutoff)
            # Support both modern (ns) and legacy (sec) Messages date encodings.
            date_filter = """
              AND (
                m.date >= ?
                OR (m.date < 1000000000000 AND m.date >= ?)
              )
            """
            params.extend([cutoff_ns, cutoff_sec])
        params.append(limit)

        rows = conn.execute(
            f"""
            SELECT
              m.ROWID AS id,
              m.text,
              m.attributedBody,
              m.is_from_me,
              m.date,
              m.cache_has_attachments,
              h.id AS handle
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE cmj.chat_id = ?
            {date_filter}
            ORDER BY m.date DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        _report(progress, "Matching contact names…", 70)
        labeled = _labeled_participants(participants)
        handle_names = resolve_handles(
            [r["handle"] for r in rows if r["handle"] and not r["is_from_me"]]
        )

        _report(progress, "Preparing messages…", 85)
        messages = []
        for row in reversed(rows):
            dt = apple_time_to_datetime(row["date"])
            text = message_text(row)
            handle = row["handle"]
            if row["is_from_me"]:
                sender = "me"
                sender_name = "You"
            else:
                sender = handle or "unknown"
                sender_name = handle_names.get(handle, display_label(handle)) if handle else "unknown"
            messages.append(
                {
                    "id": row["id"],
                    "text": text,
                    "is_from_me": bool(row["is_from_me"]),
                    "sender": sender,
                    "sender_name": sender_name,
                    "sent_at": dt.isoformat() if dt else None,
                    "has_attachments": bool(row["cache_has_attachments"]),
                }
            )

        _report(progress, f"Loaded {len(messages)} messages", 88)
        return {
            "id": chat["id"],
            "guid": chat["guid"],
            "chat_identifier": chat["chat_identifier"],
            "display_name": thread_display_name(chat, participants),
            "participants": participants,
            "participant_names": labeled,
            "messages": messages,
            "days": days,
            "cutoff_at": cutoff_iso,
        }
    finally:
        conn.close()
        cleanup_temp_db(db_path)


def access_status() -> dict[str, Any]:
    cache_dir = _messages_cache_dir()
    using_cache = bool(cache_dir and (cache_dir / "chat.db").is_file())
    live_exists = False
    try:
        live_exists = CHAT_DB.exists()
    except OSError:
        live_exists = False

    readable = False
    error: Optional[str] = None
    available_threads: Optional[int] = None
    # Prefer the launcher cache (and live DB). Do not bail just because the live
    # path is hidden/unreadable without Full Disk Access.
    try:
        conn, db_path = connect_messages()
        conn.execute("SELECT 1 FROM chat LIMIT 1")
        available_threads = int(
            conn.execute("SELECT COUNT(*) AS n FROM chat").fetchone()["n"] or 0
        )
        conn.close()
        cleanup_temp_db(db_path)
        readable = True
    except MessagesAccessError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    if not live_exists and not using_cache and not readable:
        error = error or f"Database not found at {CHAT_DB}"

    cache_db = (cache_dir / "chat.db") if cache_dir else None
    cache_size = None
    cache_mtime = None
    if cache_db is not None and cache_db.is_file():
        try:
            stat = cache_db.stat()
            cache_size = stat.st_size
            cache_mtime = stat.st_mtime
        except OSError:
            pass

    return {
        "path": str(CHAT_DB),
        "exists": live_exists or using_cache,
        "live_exists": live_exists,
        "readable": readable,
        "using_cache": using_cache,
        "cache_dir": str(cache_dir) if cache_dir else None,
        "cache_db": str(cache_db) if cache_db else None,
        "cache_size": cache_size,
        "cache_mtime": cache_mtime,
        "error": error,
        "uid": os.getuid(),
        "available_threads": available_threads,
    }
