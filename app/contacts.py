"""Resolve phone numbers and emails to macOS Contacts names."""

from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

ADDRESSBOOK_ROOT = Path.home() / "Library" / "Application Support" / "AddressBook"

_lock = threading.Lock()
_cache: dict[str, str] = {}
_cache_loaded_at = 0.0
_cache_error: Optional[str] = None
_CACHE_TTL_SECONDS = 600.0
_DEFAULT_LOAD_TIMEOUT = 6.0


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def normalize_handle(value: Optional[str]) -> list[str]:
    """Return lookup keys for a phone/email handle, most specific first."""
    if not value:
        return []
    raw = value.strip()
    if not raw:
        return []

    keys: list[str] = []
    lower = raw.lower()
    keys.append(lower)

    if "@" in raw:
        return list(dict.fromkeys(keys))

    digits = _digits(raw)
    if not digits:
        return list(dict.fromkeys(keys))

    keys.append(digits)
    if len(digits) == 11 and digits.startswith("1"):
        keys.append(digits[1:])
    if len(digits) >= 10:
        keys.append(digits[-10:])
    if not digits.startswith("1") and len(digits) == 10:
        keys.append("1" + digits)
    if digits and not raw.startswith("+"):
        keys.append("+" + digits)
    return list(dict.fromkeys(k for k in keys if k))


def _contact_name(row: sqlite3.Row) -> Optional[str]:
    first = (row["ZFIRSTNAME"] or "").strip()
    last = (row["ZLASTNAME"] or "").strip()
    nick = (row["ZNICKNAME"] or "").strip()
    org = (row["ZORGANIZATION"] or "").strip()
    name = f"{first} {last}".strip()
    if name:
        return name
    if nick:
        return nick
    if org:
        return org
    return None


def _addressbook_db_paths() -> list[Path]:
    """Prefer Sources DBs (where contact data usually lives); include root last."""
    paths: list[Path] = []
    sources = ADDRESSBOOK_ROOT / "Sources"
    if sources.is_dir():
        for path in sorted(sources.glob("*/AddressBook-v22.abcddb")):
            paths.append(path)
    root_db = ADDRESSBOOK_ROOT / "AddressBook-v22.abcddb"
    if root_db.exists():
        paths.append(root_db)
    return paths


def _open_readonly(db_path: Path) -> tuple[sqlite3.Connection, Optional[Path]]:
    """
    Open AddressBook DB read-only.
    Prefer a temp copy so WAL writers don't block; fall back to immutable open.
    """
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="contacts-ab-"))
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(db_path) + suffix) if suffix else db_path
            if candidate.exists():
                shutil.copy2(candidate, temp_dir / candidate.name)
        copied = temp_dir / db_path.name
        conn = sqlite3.connect(f"file:{copied}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        return conn, temp_dir
    except OSError:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro&immutable=1",
            uri=True,
            timeout=2,
        )
        conn.row_factory = sqlite3.Row
        return conn, None


def _add_keys(mapping: dict[str, str], value: Optional[str], name: str) -> int:
    if not value or not name:
        return 0
    added = 0
    for key in normalize_handle(value):
        if key not in mapping:
            mapping[key] = name
            added += 1
    return added


def _load_from_db(db_path: Path, mapping: dict[str, str]) -> int:
    """Load contacts with separate queries (avoids phone×email cartesian JOIN)."""
    conn, temp_dir = _open_readonly(db_path)
    added = 0
    try:
        # Quick emptiness check — root DB is often nearly empty.
        phone_count = conn.execute("SELECT COUNT(*) FROM ZABCDPHONENUMBER").fetchone()[0]
        email_count = conn.execute("SELECT COUNT(*) FROM ZABCDEMAILADDRESS").fetchone()[0]
        if phone_count == 0 and email_count == 0:
            return 0

        records = {
            int(row["Z_PK"]): row
            for row in conn.execute(
                """
                SELECT Z_PK, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZORGANIZATION
                FROM ZABCDRECORD
                """
            )
        }

        for row in conn.execute(
            """
            SELECT ZOWNER, Z22_OWNER, ZFULLNUMBER
            FROM ZABCDPHONENUMBER
            WHERE ZFULLNUMBER IS NOT NULL AND ZFULLNUMBER != ''
            """
        ):
            owner = row["ZOWNER"] or row["Z22_OWNER"]
            if owner is None:
                continue
            record = records.get(int(owner))
            if not record:
                continue
            name = _contact_name(record)
            if name:
                added += _add_keys(mapping, row["ZFULLNUMBER"], name)

        for row in conn.execute(
            """
            SELECT ZOWNER, Z22_OWNER, ZADDRESS
            FROM ZABCDEMAILADDRESS
            WHERE ZADDRESS IS NOT NULL AND ZADDRESS != ''
            """
        ):
            owner = row["ZOWNER"] or row["Z22_OWNER"]
            if owner is None:
                continue
            record = records.get(int(owner))
            if not record:
                continue
            name = _contact_name(record)
            if name:
                added += _add_keys(mapping, row["ZADDRESS"], name)
    finally:
        conn.close()
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
    return added


def _load_all_dbs() -> tuple[dict[str, str], Optional[str]]:
    mapping: dict[str, str] = {}
    error: Optional[str] = None
    db_paths = _addressbook_db_paths()
    if not db_paths:
        return mapping, f"No AddressBook database found under {ADDRESSBOOK_ROOT}"

    for db_path in db_paths:
        try:
            _load_from_db(db_path, mapping)
            # One good Sources DB is enough for names.
            if mapping:
                break
        except PermissionError:
            error = (
                "Permission denied reading Contacts. Grant Full Disk Access "
                "to the app running this server, then restart."
            )
            raise
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            continue

    if not mapping and error is None:
        error = "Contacts database was readable but no phone/email entries were found."
    return mapping, error


def refresh_contacts(
    force: bool = False,
    timeout: Optional[float] = _DEFAULT_LOAD_TIMEOUT,
) -> dict[str, str]:
    """
    Load/refresh the contacts map.
    Uses a timeout so Messages loading is never blocked indefinitely.
    """
    global _cache, _cache_loaded_at, _cache_error
    now = time.time()

    with _lock:
        if (
            not force
            and _cache
            and (now - _cache_loaded_at) < _CACHE_TTL_SECONDS
        ):
            return _cache

    if timeout is None or timeout <= 0:
        with _lock:
            try:
                mapping, error = _load_all_dbs()
                _cache = mapping
                _cache_loaded_at = time.time()
                _cache_error = None if mapping else error
            except PermissionError as exc:
                _cache = {}
                _cache_loaded_at = time.time()
                _cache_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                _cache = {}
                _cache_loaded_at = time.time()
                _cache_error = str(exc)
            return _cache

    result: dict[str, Any] = {"mapping": None, "error": None}

    def worker() -> None:
        try:
            mapping, error = _load_all_dbs()
            result["mapping"] = mapping
            result["error"] = error
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
            result["mapping"] = {}

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    with _lock:
        if thread.is_alive():
            # Keep any previous cache; mark a soft timeout error.
            if not _cache:
                _cache_error = (
                    f"Contacts load timed out after {timeout:.0f}s — "
                    "showing phone numbers for now."
                )
                _cache_loaded_at = time.time()
            else:
                _cache_error = (
                    f"Contacts refresh timed out after {timeout:.0f}s — "
                    "using cached names."
                )
            return _cache

        mapping = result.get("mapping")
        if isinstance(mapping, dict):
            _cache = mapping
            _cache_loaded_at = time.time()
            _cache_error = None if mapping else result.get("error")
        elif result.get("error"):
            if not _cache:
                _cache = {}
            _cache_error = str(result["error"])
            _cache_loaded_at = time.time()
        return _cache


def resolve_handle(handle: Optional[str]) -> Optional[str]:
    if not handle:
        return None
    mapping = refresh_contacts()
    for key in normalize_handle(handle):
        name = mapping.get(key)
        if name:
            return name
    return None


def resolve_handles(handles: list[str]) -> dict[str, str]:
    mapping = refresh_contacts()
    out: dict[str, str] = {}
    for handle in handles:
        if not handle:
            continue
        for key in normalize_handle(handle):
            name = mapping.get(key)
            if name:
                out[handle] = name
                break
    return out


def display_label(handle: Optional[str]) -> str:
    """Contact name if known, otherwise the original handle."""
    if not handle:
        return "unknown"
    return resolve_handle(handle) or handle


def looks_like_handle(value: Optional[str]) -> bool:
    if not value:
        return False
    text = value.strip()
    if "@" in text:
        return True
    digits = _digits(text)
    return len(digits) >= 7 and len(digits) / max(len(text), 1) >= 0.6


def contacts_status(*, quick: bool = False) -> dict[str, Any]:
    if quick:
        with _lock:
            return {
                "available": bool(_cache) and _cache_error is None,
                "contact_keys": len(_cache),
                "error": _cache_error,
                "path": str(ADDRESSBOOK_ROOT),
                "cached": bool(_cache),
            }
    mapping = refresh_contacts(timeout=3.0)
    return {
        "available": bool(mapping) and _cache_error is None,
        "contact_keys": len(mapping),
        "error": _cache_error,
        "path": str(ADDRESSBOOK_ROOT),
        "cached": bool(mapping),
    }
