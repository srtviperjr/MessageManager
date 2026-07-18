"""Refresh Messages + Contacts caches with progress (large chat.db support)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from app.logging_util import get_logger, log_dir

log = get_logger("messagemanager.cache")

ProgressFn = Callable[[str, int], None]

CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB
_refresh_lock = threading.Lock()


def _app_support() -> Path:
    return Path.home() / "Library" / "Application Support" / "MessageManager"


def messages_cache_dir() -> Path:
    raw = (os.environ.get("THREAD_LEDGER_MESSAGES_CACHE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _app_support() / "messages-cache"


def contacts_cache_dir() -> Path:
    raw = (os.environ.get("THREAD_LEDGER_CONTACTS_CACHE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _app_support() / "contacts-cache"


def progress_file_path() -> Path:
    return log_dir() / "cache-refresh.json"


def _report(
    progress: Optional[ProgressFn],
    message: str,
    percent: int,
    **extra: Any,
) -> None:
    pct = max(0, min(100, int(percent)))
    if progress:
        progress(message, pct)
    payload = {
        "message": message,
        "percent": pct,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    try:
        path = progress_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def _format_bytes(n: int) -> str:
    if n >= 1024**3:
        return f"{n / (1024**3):.2f} GB"
    if n >= 1024**2:
        return f"{n / (1024**2):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _copy_file_chunked(
    src: Path,
    dst: Path,
    *,
    label: str,
    progress: Optional[ProgressFn],
    percent_start: int,
    percent_end: int,
) -> dict[str, Any]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    partial = dst.with_suffix(dst.suffix + ".partial")
    try:
        if partial.exists():
            partial.unlink()
    except OSError:
        pass

    total = src.stat().st_size
    copied = 0
    last_report = 0.0
    with src.open("rb") as rin, partial.open("wb") as rout:
        while True:
            chunk = rin.read(CHUNK_SIZE)
            if not chunk:
                break
            rout.write(chunk)
            copied += len(chunk)
            now = time.monotonic()
            if now - last_report >= 0.2 or copied >= total:
                last_report = now
                frac = (copied / total) if total else 1.0
                pct = percent_start + int((percent_end - percent_start) * frac)
                _report(
                    progress,
                    f"Copying {label}: {_format_bytes(copied)} / {_format_bytes(total)}",
                    pct,
                    bytes_copied=copied,
                    bytes_total=total,
                    current_file=str(src),
                )
    partial.replace(dst)
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass
    return {"path": str(dst), "bytes": total}


def _copy_db_trio(
    src_db: Path,
    dst_db: Path,
    *,
    label: str,
    progress: Optional[ProgressFn],
    percent_start: int,
    percent_end: int,
) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    parts = [src_db, Path(str(src_db) + "-wal"), Path(str(src_db) + "-shm")]
    existing = [p for p in parts if p.is_file()]
    if not existing:
        raise FileNotFoundError(f"Missing {src_db}")

    weights = [max(p.stat().st_size, 1) for p in existing]
    weight_sum = sum(weights)
    cursor = percent_start
    for src, weight in zip(existing, weights):
        span = max(1, int((percent_end - percent_start) * (weight / weight_sum)))
        end = min(percent_end, cursor + span)
        suffix = src.name[len(src_db.name) :]  # "", "-wal", "-shm"
        dst = Path(str(dst_db) + suffix) if suffix else dst_db
        part_label = f"{label}{suffix}" if suffix else label
        info = _copy_file_chunked(
            src,
            dst,
            label=part_label,
            progress=progress,
            percent_start=cursor,
            percent_end=end,
        )
        copied.append(info)
        cursor = end
    return copied


def _find_macos_binary() -> Optional[Path]:
    env = (os.environ.get("MESSAGEMANAGER_BINARY") or "").strip()
    if env and Path(env).is_file():
        return Path(env)
    apps = Path("/Applications/MessageManager.app/Contents/MacOS/MessageManager")
    if apps.is_file():
        return apps
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name.endswith(".app"):
            candidate = parent / "Contents" / "MacOS" / "MessageManager"
            if candidate.is_file():
                return candidate
        if parent.name == "Contents":
            candidate = parent / "MacOS" / "MessageManager"
            if candidate.is_file():
                return candidate
    return None


def _refresh_contacts_python(progress: Optional[ProgressFn]) -> dict[str, Any]:
    live_root = Path.home() / "Library" / "Application Support" / "AddressBook"
    cache = contacts_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    root_db = live_root / "AddressBook-v22.abcddb"
    if root_db.is_file():
        results.extend(
            _copy_db_trio(
                root_db,
                cache / "AddressBook-v22.abcddb",
                label="Contacts",
                progress=progress,
                percent_start=78,
                percent_end=88,
            )
        )

    sources = live_root / "Sources"
    if sources.is_dir():
        children = [p for p in sources.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if children:
            span = 10 / len(children)
            for i, child in enumerate(children):
                src_db = child / "AddressBook-v22.abcddb"
                if not src_db.is_file():
                    continue
                start = 88 + int(i * span)
                end = 88 + int((i + 1) * span)
                dst_dir = cache / "Sources" / child.name
                dst_dir.mkdir(parents=True, exist_ok=True)
                results.extend(
                    _copy_db_trio(
                        src_db,
                        dst_dir / "AddressBook-v22.abcddb",
                        label=f"Contacts/{child.name[:8]}",
                        progress=progress,
                        percent_start=start,
                        percent_end=end,
                    )
                )
    return {"copied": results, "cache_dir": str(cache)}


def refresh_caches_python(progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """Copy live Messages + Contacts into Application Support caches (chunked)."""
    live_db = Path.home() / "Library" / "Messages" / "chat.db"
    if not live_db.is_file():
        raise FileNotFoundError(
            f"Messages database not found at {live_db}. Open Messages once, then retry."
        )

    msg_cache = messages_cache_dir()
    msg_cache.mkdir(parents=True, exist_ok=True)

    _report(progress, "Preparing Messages cache…", 2)
    try:
        messages = _copy_db_trio(
            live_db,
            msg_cache / "chat.db",
            label="Messages chat.db",
            progress=progress,
            percent_start=5,
            percent_end=75,
        )
    except PermissionError as exc:
        raise PermissionError(
            "Permission denied reading Messages. Grant Full Disk Access to "
            "MessageManager.app and Python.app, then quit and reopen — or retry Refresh cache."
        ) from exc

    _report(progress, "Copying Contacts…", 78)
    try:
        contacts = _refresh_contacts_python(progress)
    except PermissionError:
        contacts = {
            "copied": [],
            "cache_dir": str(contacts_cache_dir()),
            "error": "Contacts copy skipped (permission denied)",
        }
    except OSError as exc:
        contacts = {
            "copied": [],
            "cache_dir": str(contacts_cache_dir()),
            "error": str(exc),
        }

    cached = msg_cache / "chat.db"
    result = {
        "ok": True,
        "method": "python",
        "messages_cache": str(msg_cache),
        "messages_bytes": cached.stat().st_size if cached.is_file() else 0,
        "messages_files": messages,
        "contacts": contacts,
    }
    _report(progress, "Cache refresh complete", 100, done=True, result=result)
    return result


def refresh_caches_native(progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """Run MessageManager --refresh-cache so FDA on the app binary applies."""
    binary = _find_macos_binary()
    if binary is None:
        raise FileNotFoundError("MessageManager.app binary not found")

    status_path = progress_file_path()
    try:
        if status_path.exists():
            status_path.unlink()
    except OSError:
        pass

    _report(progress, "Starting native cache refresh…", 1)
    # Prefer LaunchServices (-n new instance) so TCC treats this as MessageManager.app.
    # Fall back to executing the binary directly.
    app_bundle = binary.parent.parent.parent  # …/MessageManager.app
    if app_bundle.name.endswith(".app"):
        proc = subprocess.Popen(  # noqa: S603
            [
                "open",
                "-n",
                "-W",
                "-a",
                str(app_bundle),
                "--args",
                "--refresh-cache",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        proc = subprocess.Popen(  # noqa: S603
            [str(binary), "--refresh-cache"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    result: Optional[dict[str, Any]] = None
    deadline = time.monotonic() + 60 * 60  # 1 hour for very large DBs
    while time.monotonic() < deadline:
        if status_path.is_file():
            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            msg = data.get("message") or "Copying…"
            pct = int(data.get("percent") or 0)
            if progress:
                progress(msg, pct)
            if data.get("error") and data.get("done"):
                raise RuntimeError(data["error"])
            if data.get("done"):
                result = data.get("result") or data
                break
        if proc.poll() is not None:
            time.sleep(0.4)
            if status_path.is_file():
                try:
                    data = json.loads(status_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = {}
                if data.get("error"):
                    raise RuntimeError(data["error"])
                if data.get("done"):
                    result = data.get("result") or data
                    break
            if result is None and proc.returncode not in (0, None):
                raise RuntimeError(
                    f"Native cache refresh failed (exit {proc.returncode}). "
                    "Grant Full Disk Access to MessageManager.app, quit, and reopen."
                )
            if result is None and proc.returncode == 0:
                # open -W returned; status may still be incomplete
                cached = messages_cache_dir() / "chat.db"
                if cached.is_file():
                    result = {"ok": True, "method": "native"}
                    break
            if result is None and proc.returncode == 0:
                break
        time.sleep(0.25)

    if result is None:
        if proc.poll() is None:
            proc.terminate()
        raise TimeoutError("Cache refresh timed out")

    if result.get("error"):
        raise RuntimeError(result["error"])
    cached = messages_cache_dir() / "chat.db"
    if not cached.is_file():
        raise RuntimeError(
            "Cache refresh finished but messages-cache/chat.db is still missing. "
            "Grant Full Disk Access to MessageManager.app, quit, and reopen."
        )
    result.setdefault("method", "native")
    result["ok"] = True
    result["messages_cache"] = str(messages_cache_dir())
    result["messages_bytes"] = cached.stat().st_size
    _report(progress, "Cache refresh complete", 100, done=True)
    return result


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "scripts" / "macos"


def terminal_sync_paths() -> dict[str, Optional[str]]:
    base = _scripts_dir()
    py = base / "sync-messages-cache.py"
    command = base / "sync-messages-cache.command"
    return {
        "script": str(py) if py.is_file() else None,
        "command": str(command) if command.is_file() else None,
        "dir": str(base) if base.is_dir() else None,
    }


def _install_terminal_sync_copy() -> Path:
    """
    Copy the Terminal sync helper into Application Support so it can be opened
    even if the app bundle path is awkward, and so FDA guidance is stable.
    """
    paths = terminal_sync_paths()
    if not paths.get("script"):
        raise FileNotFoundError("sync-messages-cache.py missing from app bundle")
    dest_dir = _app_support() / "bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_py = dest_dir / "sync-messages-cache.py"
    dest_cmd = dest_dir / "sync-messages-cache.command"
    shutil.copy2(paths["script"], dest_py)
    dest_cmd.write_text(
        "#!/bin/bash\n"
        "export KEEP_TERMINAL_OPEN=1\n"
        f'DIR="{dest_dir}"\n'
        'cd "${DIR}"\n'
        'echo "If copy fails: enable Full Disk Access for Terminal.app, quit Terminal, reopen."\n'
        'exec /usr/bin/env python3 "${DIR}/sync-messages-cache.py"\n',
        encoding="utf-8",
    )
    try:
        dest_py.chmod(dest_py.stat().st_mode | 0o111)
        dest_cmd.chmod(dest_cmd.stat().st_mode | 0o111)
    except OSError:
        pass
    return dest_cmd


def _poll_progress_file(
    progress: Optional[ProgressFn],
    *,
    proc: Optional[subprocess.Popen] = None,
    timeout_s: float = 60 * 60,
) -> dict[str, Any]:
    status_path = progress_file_path()
    result: Optional[dict[str, Any]] = None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if status_path.is_file():
            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            msg = data.get("message") or "Copying…"
            pct = int(data.get("percent") or 0)
            if progress:
                progress(msg, pct)
            if data.get("error") and data.get("done"):
                raise RuntimeError(data["error"])
            if data.get("done"):
                result = data.get("result") or data
                break
        if proc is not None and proc.poll() is not None:
            time.sleep(0.4)
            if status_path.is_file():
                try:
                    data = json.loads(status_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = {}
                if data.get("error") and data.get("done"):
                    raise RuntimeError(data["error"])
                if data.get("done"):
                    result = data.get("result") or data
                    break
            if result is None and proc.returncode not in (0, None):
                raise RuntimeError(
                    f"Cache sync exited with code {proc.returncode}. "
                    "Enable Full Disk Access for Terminal.app, quit Terminal, and retry."
                )
            if result is None and proc.returncode == 0:
                cached = messages_cache_dir() / "chat.db"
                if cached.is_file():
                    result = {"ok": True, "method": "terminal"}
                    break
        time.sleep(0.25)

    if result is None:
        if proc is not None and proc.poll() is None:
            proc.terminate()
        raise TimeoutError("Cache sync timed out")

    cached = messages_cache_dir() / "chat.db"
    if not cached.is_file():
        raise RuntimeError(
            "Sync finished but messages-cache/chat.db is still missing. "
            "Enable Full Disk Access for Terminal.app, quit Terminal, reopen, and retry."
        )
    result.setdefault("method", "terminal")
    result["ok"] = True
    result["messages_cache"] = str(messages_cache_dir())
    result["messages_bytes"] = cached.stat().st_size
    _report(progress, "Cache sync complete", 100, done=True)
    return result


def refresh_caches_via_terminal(progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """
    Open Terminal.app to run the cache sync script.

    Terminal's Full Disk Access is what previously worked on the Tahoe Mac
    when MessageManager was run from the terminal before the cache redesign.
    """
    status_path = progress_file_path()
    try:
        if status_path.exists():
            status_path.unlink()
    except OSError:
        pass

    command = _install_terminal_sync_copy()
    _report(
        progress,
        "Opening Terminal to sync cache (uses Terminal Full Disk Access)…",
        1,
    )
    # Reveal + launch so the user can grant FDA to Terminal if needed.
    try:
        subprocess.Popen(["open", "-R", str(command)])  # noqa: S603
    except OSError:
        pass
    proc = subprocess.Popen(  # noqa: S603
        ["open", "-a", "Terminal", str(command)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # `open` returns quickly; the Terminal script keeps writing progress.
    time.sleep(0.5)
    if proc.poll() not in (0, None) and proc.returncode not in (0, None):
        raise RuntimeError("Could not open Terminal to run the cache sync script")

    return _poll_progress_file(progress, proc=None, timeout_s=60 * 60)


def open_terminal_sync() -> dict[str, Any]:
    """Launch the Terminal sync helper without waiting (manual Recheck afterward)."""
    command = _install_terminal_sync_copy()
    try:
        subprocess.Popen(["open", "-R", str(command)])  # noqa: S603
    except OSError:
        pass
    subprocess.Popen(  # noqa: S603
        ["open", "-a", "Terminal", str(command)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {
        "ok": True,
        "command": str(command),
        "detail": (
            "Opened Terminal cache sync. If it fails, enable Full Disk Access for "
            "Terminal.app, quit Terminal, reopen, and run again. Then Recheck in MessageManager."
        ),
    }


def refresh_caches(progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """
    Refresh Messages/Contacts caches with progress.

    Order:
      1) Native MessageManager --refresh-cache (app FDA)
      2) Terminal sync script (Terminal FDA — works on Tahoe when app FDA does not)
      3) In-process Python copy (dev / when the server itself has FDA)
    """
    if not _refresh_lock.acquire(blocking=False):
        raise RuntimeError("A cache refresh is already running")
    try:
        errors: list[str] = []
        binary = _find_macos_binary()
        if binary is not None and os.environ.get("THREAD_LEDGER_MANAGED") == "1":
            try:
                return refresh_caches_native(progress)
            except Exception as native_exc:  # noqa: BLE001
                log.warning("Native cache refresh failed: %s", native_exc)
                errors.append(f"app: {native_exc}")
                _report(
                    progress,
                    "App copy blocked — opening Terminal sync (use Terminal Full Disk Access)…",
                    2,
                )
                try:
                    return refresh_caches_via_terminal(progress)
                except Exception as term_exc:  # noqa: BLE001
                    log.warning("Terminal cache sync failed: %s", term_exc)
                    errors.append(f"terminal: {term_exc}")
                    _report(progress, "Terminal sync failed — trying Python copy…", 3)

        try:
            return refresh_caches_python(progress)
        except Exception as py_exc:  # noqa: BLE001
            errors.append(f"python: {py_exc}")
            raise RuntimeError(
                "Could not refresh cache. On this Mac, enable Full Disk Access for "
                "Terminal.app (System Settings → Privacy & Security → Full Disk Access), "
                "quit Terminal, reopen it, then use Refresh cache / Sync via Terminal. "
                f"Details: {' | '.join(errors)}"
            ) from py_exc
    finally:
        _refresh_lock.release()


def cache_status() -> dict[str, Any]:
    msg = messages_cache_dir() / "chat.db"
    live = Path.home() / "Library" / "Messages" / "chat.db"
    info: dict[str, Any] = {
        "messages_cache_dir": str(messages_cache_dir()),
        "messages_cache_exists": msg.is_file(),
        "messages_cache_bytes": msg.stat().st_size if msg.is_file() else None,
        "live_db_exists": False,
        "live_db_bytes": None,
        "terminal_sync": terminal_sync_paths(),
    }
    try:
        if live.is_file():
            info["live_db_exists"] = True
            info["live_db_bytes"] = live.stat().st_size
    except OSError as exc:
        info["live_db_error"] = str(exc)
    return info
