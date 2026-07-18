#!/usr/bin/env python3
"""
Copy Messages (+ Contacts) into MessageManager's cache.

This script is meant to run inside Terminal.app (or iTerm, etc.).
On macOS Tahoe, Full Disk Access often works for Terminal even when it does
not stick for MessageManager.app — which matches the earlier “run from Terminal”
setup that worked on the other Mac.

Usage:
  python3 sync-messages-cache.py
  # or double-click sync-messages-cache.command
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

CHUNK = 8 * 1024 * 1024
HOME = Path.home()
APP_SUPPORT = HOME / "Library" / "Application Support" / "MessageManager"
MSG_CACHE = APP_SUPPORT / "messages-cache"
CONTACTS_CACHE = APP_SUPPORT / "contacts-cache"
LOG_DIR = APP_SUPPORT / "logs"
PROGRESS = LOG_DIR / "cache-refresh.json"
LIVE_DB = HOME / "Library" / "Messages" / "chat.db"
LIVE_AB = HOME / "Library" / "Application Support" / "AddressBook"


def report(message: str, percent: int, *, done: bool = False, error: str | None = None) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "message": message,
        "percent": max(0, min(100, int(percent))),
        "done": done,
        "method": "terminal",
        "ok": done and not error,
    }
    if error:
        payload["error"] = error
    PROGRESS.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    print(f"[{payload['percent']:3d}%] {message}", flush=True)
    if error:
        print(f"ERROR: {error}", flush=True)


def fmt(n: int) -> str:
    if n >= 1024**3:
        return f"{n / (1024**3):.2f} GB"
    if n >= 1024**2:
        return f"{n / (1024**2):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def copy_file(src: Path, dst: Path, label: str, start: int, end: int) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    partial = dst.with_suffix(dst.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    total = src.stat().st_size
    copied = 0
    last = 0.0
    with src.open("rb") as rin, partial.open("wb") as rout:
        while True:
            chunk = rin.read(CHUNK)
            if not chunk:
                break
            rout.write(chunk)
            copied += len(chunk)
            now = time.monotonic()
            if now - last >= 0.25 or copied >= total:
                last = now
                frac = copied / total if total else 1.0
                pct = start + int((end - start) * frac)
                report(
                    f"Copying {label}: {fmt(copied)} / {fmt(total)}",
                    pct,
                )
    partial.replace(dst)
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass
    return total


def copy_trio(src_db: Path, dst_db: Path, label: str, start: int, end: int) -> int:
    total = 0
    parts = [src_db, Path(str(src_db) + "-wal"), Path(str(src_db) + "-shm")]
    existing = [p for p in parts if p.is_file()]
    if not existing:
        raise FileNotFoundError(str(src_db))
    weights = [max(p.stat().st_size, 1) for p in existing]
    wsum = sum(weights)
    cursor = start
    for src, weight in zip(existing, weights):
        span = max(1, int((end - start) * (weight / wsum)))
        stop = min(end, cursor + span)
        suffix = src.name[len(src_db.name) :]
        dst = Path(str(dst_db) + suffix) if suffix else dst_db
        total += copy_file(src, dst, f"{label}{suffix}", cursor, stop)
        cursor = stop
    return total


def copy_contacts() -> None:
    report("Copying Contacts…", 80)
    CONTACTS_CACHE.mkdir(parents=True, exist_ok=True)
    root_db = LIVE_AB / "AddressBook-v22.abcddb"
    if root_db.is_file():
        copy_trio(root_db, CONTACTS_CACHE / "AddressBook-v22.abcddb", "Contacts", 80, 88)
    sources = LIVE_AB / "Sources"
    if not sources.is_dir():
        return
    children = [p for p in sources.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not children:
        return
    span = 10 / len(children)
    for i, child in enumerate(children):
        src = child / "AddressBook-v22.abcddb"
        if not src.is_file():
            continue
        start = 88 + int(i * span)
        end = 88 + int((i + 1) * span)
        dst_dir = CONTACTS_CACHE / "Sources" / child.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        copy_trio(src, dst_dir / "AddressBook-v22.abcddb", f"Contacts/{child.name[:8]}", start, end)


def main() -> int:
    print()
    print("MessageManager — Terminal cache sync")
    print("====================================")
    print("Uses Full Disk Access from THIS Terminal app (not MessageManager.app).")
    print("If this fails: System Settings → Privacy & Security → Full Disk Access")
    print("→ enable Terminal (or iTerm), quit Terminal, reopen, run again.")
    print()

    report("Starting Terminal cache sync…", 1)
    if not LIVE_DB.is_file():
        report(
            "Messages database not found",
            0,
            done=True,
            error=f"Missing {LIVE_DB}. Open Messages once, then retry.",
        )
        return 1

    try:
        # Prove we can read before starting a long copy.
        with LIVE_DB.open("rb") as fh:
            fh.read(1)
    except PermissionError:
        report(
            "Permission denied reading Messages",
            0,
            done=True,
            error=(
                "Terminal does not have Full Disk Access. Enable FDA for Terminal.app, "
                "fully quit Terminal, reopen, and run this again."
            ),
        )
        return 2
    except OSError as exc:
        report("Could not read Messages", 0, done=True, error=str(exc))
        return 2

    try:
        MSG_CACHE.mkdir(parents=True, exist_ok=True)
        size = copy_trio(LIVE_DB, MSG_CACHE / "chat.db", "Messages chat.db", 5, 75)
        try:
            copy_contacts()
        except PermissionError:
            print("Contacts copy skipped (permission denied).", flush=True)
        except OSError as exc:
            print(f"Contacts copy skipped: {exc}", flush=True)
        report(f"Cache sync complete ({fmt(size)})", 100, done=True)
        print()
        print(f"Wrote: {MSG_CACHE / 'chat.db'}")
        print("Return to MessageManager and press Recheck / Start loading.")
        print()
        return 0
    except PermissionError:
        report(
            "Permission denied during copy",
            0,
            done=True,
            error="Full Disk Access missing for this Terminal. Enable it, quit Terminal, retry.",
        )
        return 2
    except OSError as exc:
        report("Cache sync failed", 0, done=True, error=str(exc))
        return 3


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        if os.environ.get("KEEP_TERMINAL_OPEN") == "1":
            try:
                input("Press Return to close…")
            except EOFError:
                pass
    raise SystemExit(code)
