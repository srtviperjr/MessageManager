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


def last_sync_meta_path() -> Path:
    return log_dir() / "cache-last-sync.json"


def _write_last_sync_meta(result: dict[str, Any]) -> None:
    """Persist when/how the cache was last successfully synced."""
    payload = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "method": result.get("method") or "unknown",
        "messages_bytes": result.get("messages_bytes"),
        "messages_cache": result.get("messages_cache"),
        "python_app": result.get("python_app"),
    }
    try:
        path = last_sync_meta_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def _read_last_sync_meta() -> Optional[dict[str, Any]]:
    path = last_sync_meta_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _file_freshness(path: Path) -> dict[str, Any]:
    """Size / mtime / age for a cache or live DB file."""
    info: dict[str, Any] = {
        "exists": False,
        "path": str(path),
        "bytes": None,
        "mtime": None,
        "mtime_iso": None,
        "age_seconds": None,
    }
    try:
        if not path.is_file():
            return info
        st = path.stat()
        age = max(0.0, time.time() - st.st_mtime)
        info.update(
            {
                "exists": True,
                "bytes": st.st_size,
                "mtime": st.st_mtime,
                "mtime_iso": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
                "age_seconds": int(age),
            }
        )
    except OSError as exc:
        info["error"] = str(exc)
    return info


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


def _install_sync_helpers() -> tuple[Path, Path]:
    """
    Copy sync helpers into Application Support.
    Returns (script.py, terminal.command).
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
        "export MESSAGEMANAGER_SYNC_METHOD=terminal\n"
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
    return dest_py, dest_cmd


def _framework_python_apps() -> list[Path]:
    """python.org Framework Python.app bundles, newest first."""
    found: list[Path] = []
    for version in ("3.13", "3.12", "3.11", "3.10", "3.9"):
        candidate = Path(
            f"/Library/Frameworks/Python.framework/Versions/{version}/Resources/Python.app"
        )
        if candidate.is_dir():
            found.append(candidate)
    return found


def _python_app_executable(app: Path) -> Optional[Path]:
    """Return the Mach-O inside Python.app (TCC identity matches the .app)."""
    for name in ("Python", "python3", "Python3"):
        candidate = app / "Contents" / "MacOS" / name
        if candidate.is_file():
            return candidate
    return None


def _framework_python_launcher() -> tuple[Optional[Path], Optional[Path]]:
    """
    Return (python_executable, python_app) for an out-of-process sync that can
    use Python.app Full Disk Access (more stable than MessageManager.app on Tahoe).

    Prefer the Python.app bundle binary only — never fall back to a bare
    .../bin/python3 for FDA-sensitive work (that identity often is not what the
    user enabled in Full Disk Access).
    """
    from app.runtime_info import python_fda_target

    target = python_fda_target()
    app: Optional[Path] = Path(target) if target else None
    if app is not None and not str(app).endswith(".app"):
        app = None
    if app is None or not app.is_dir():
        apps = _framework_python_apps()
        app = apps[0] if apps else None

    exe = _python_app_executable(app) if app is not None else None
    if exe is None:
        for candidate_app in _framework_python_apps():
            exe = _python_app_executable(candidate_app)
            if exe is not None:
                app = candidate_app
                break
    return exe, app if app and app.is_dir() else None


def _popen_via_python_app(
    args: list[str],
    *,
    env: Optional[dict[str, str]] = None,
) -> subprocess.Popen:
    """
    Launch a script under Python.app via LaunchServices when possible.

    `open -a Python.app` keeps the TCC identity as Python.app (the entry users
    toggle in Full Disk Access). Falls back to the bundle Mach-O directly.
    """
    exe, app = _framework_python_launcher()
    if exe is None:
        raise FileNotFoundError(
            "python.org Python.app not found. Install Python from python.org, "
            "grant Full Disk Access to Python.app, then retry."
        )
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    if app is not None and app.is_dir():
        # -n: new instance; -W: wait until it exits (so callers can poll).
        return subprocess.Popen(  # noqa: S603
            ["open", "-n", "-W", "-a", str(app), "--args", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=run_env,
        )
    return subprocess.Popen(  # noqa: S603
        [str(exe), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=run_env,
    )


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
                    "Enable Full Disk Access for the selected sync method and retry."
                )
            if result is None and proc.returncode == 0:
                cached = messages_cache_dir() / "chat.db"
                if cached.is_file():
                    result = {"ok": True}
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
            "Enable Full Disk Access for the selected method, quit related apps, and retry."
        )
    result.setdefault("method", "unknown")
    result["ok"] = True
    result["messages_cache"] = str(messages_cache_dir())
    result["messages_bytes"] = cached.stat().st_size
    _write_last_sync_meta(result)
    _report(progress, "Cache sync complete", 100, done=True)
    return result


def refresh_caches_via_python_app(progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """
    Run the sync script with Framework / Python.app so Python's FDA applies.

    Prefer this on Tahoe: Python.app is reinstalled less often than MessageManager.
    """
    status_path = progress_file_path()
    try:
        if status_path.exists():
            status_path.unlink()
    except OSError:
        pass

    script, _command = _install_sync_helpers()
    exe, app = _framework_python_launcher()
    if exe is None:
        raise FileNotFoundError(
            "python.org Python.app not found. Install Python from python.org, "
            "grant Full Disk Access to Python.app, then retry."
        )

    _report(
        progress,
        f"Starting Python cache sync via {app.name if app else exe.name}…",
        1,
    )
    env = {
        "MESSAGEMANAGER_SYNC_METHOD": "python",
    }
    # Launch through Python.app so Full Disk Access matches the FDA list entry.
    proc = _popen_via_python_app(
        [str(script), "--method", "python"],
        env=env,
    )
    result = _poll_progress_file(progress, proc=proc, timeout_s=60 * 60)
    result["method"] = "python"
    result["python_app"] = str(app) if app else None
    result["python_executable"] = str(exe)
    return result


def refresh_caches_via_terminal(progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """Open Terminal.app to run the cache sync script (Terminal FDA)."""
    status_path = progress_file_path()
    try:
        if status_path.exists():
            status_path.unlink()
    except OSError:
        pass

    _script, command = _install_sync_helpers()
    _report(
        progress,
        "Opening Terminal to sync cache (uses Terminal Full Disk Access)…",
        1,
    )
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
    time.sleep(0.5)
    if proc.poll() not in (0, None) and proc.returncode not in (0, None):
        raise RuntimeError("Could not open Terminal to run the cache sync script")

    result = _poll_progress_file(progress, proc=None, timeout_s=60 * 60)
    result["method"] = "terminal"
    return result


def open_terminal_sync() -> dict[str, Any]:
    """Launch the Terminal sync helper without waiting (manual Recheck afterward)."""
    _script, command = _install_sync_helpers()
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


def open_python_sync() -> dict[str, Any]:
    """Launch Framework Python.app to run the cache sync (non-blocking)."""
    script, _command = _install_sync_helpers()
    exe, app = _framework_python_launcher()
    if exe is None:
        raise FileNotFoundError(
            "python.org Python.app not found. Install Python from python.org, "
            "grant Full Disk Access to Python.app, then retry."
        )
    status_path = progress_file_path()
    try:
        if status_path.exists():
            status_path.unlink()
    except OSError:
        pass
    # Non-blocking: omit -W by launching a short open without wait via helper
    # that still uses LaunchServices identity.
    if app is not None and app.is_dir():
        subprocess.Popen(  # noqa: S603
            [
                "open",
                "-n",
                "-a",
                str(app),
                "--args",
                str(script),
                "--method",
                "python",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "MESSAGEMANAGER_SYNC_METHOD": "python"},
        )
    else:
        _popen_via_python_app(
            [str(script), "--method", "python"],
            env={"MESSAGEMANAGER_SYNC_METHOD": "python"},
        )
    return {
        "ok": True,
        "script": str(script),
        "python_app": str(app) if app else None,
        "python_executable": str(exe),
        "detail": (
            f"Started Python cache sync via {app or exe}. "
            "Enable Full Disk Access for Python.app if it fails, then Retest and Sync again."
        ),
    }


def refresh_caches(
    progress: Optional[ProgressFn] = None,
    *,
    method: Optional[str] = None,
) -> dict[str, Any]:
    """
    Refresh Messages/Contacts caches with progress using the chosen method.

    Methods:
      - python: Framework Python.app (default; stable FDA on Tahoe)
      - terminal: Terminal.app FDA (workaround)
    """
    from app import settings as settings_store

    if not _refresh_lock.acquire(blocking=False):
        raise RuntimeError("A cache refresh is already running")
    try:
        settings = settings_store.get_settings()
        chosen = (method or settings.get("cache_sync_method") or "python").lower()
        if chosen == "app":
            chosen = "python"
        if chosen not in {"python", "terminal"}:
            chosen = "python"

        if chosen == "terminal":
            _report(progress, "Syncing cache with Terminal…", 1)
            return refresh_caches_via_terminal(progress)

        _report(progress, "Syncing cache with Python.app…", 1)
        return refresh_caches_via_python_app(progress)
    finally:
        _refresh_lock.release()


def cache_status() -> dict[str, Any]:
    from app import settings as settings_store
    from app.runtime_info import runtime_status

    msg = messages_cache_dir() / "chat.db"
    live = Path.home() / "Library" / "Messages" / "chat.db"
    contacts = contacts_cache_dir() / "AddressBook-v22.abcddb"
    exe, app = _framework_python_launcher()
    cache_info = _file_freshness(msg)
    live_info = _file_freshness(live)
    contacts_info = _file_freshness(contacts)
    last_sync = _read_last_sync_meta()

    # Prefer explicit last-sync stamp; fall back to cache file mtime.
    last_synced_at = None
    last_sync_method = None
    last_sync_age_seconds = None
    if last_sync and last_sync.get("synced_at"):
        last_synced_at = str(last_sync["synced_at"])
        last_sync_method = last_sync.get("method")
        try:
            synced = datetime.fromisoformat(last_synced_at.replace("Z", "+00:00"))
            last_sync_age_seconds = int(
                max(0.0, (datetime.now(timezone.utc) - synced).total_seconds())
            )
        except ValueError:
            last_sync_age_seconds = cache_info.get("age_seconds")
    elif cache_info.get("exists"):
        last_synced_at = cache_info.get("mtime_iso")
        last_sync_age_seconds = cache_info.get("age_seconds")
        last_sync_method = "unknown"

    live_newer = False
    if (
        cache_info.get("mtime") is not None
        and live_info.get("mtime") is not None
        and live_info["mtime"] > cache_info["mtime"] + 2
    ):
        live_newer = True

    info: dict[str, Any] = {
        "messages_cache_dir": str(messages_cache_dir()),
        "messages_cache_exists": bool(cache_info.get("exists")),
        "messages_cache_bytes": cache_info.get("bytes"),
        "messages_cache_mtime": cache_info.get("mtime"),
        "messages_cache_mtime_iso": cache_info.get("mtime_iso"),
        "messages_cache_age_seconds": cache_info.get("age_seconds"),
        "contacts_cache_exists": bool(contacts_info.get("exists")),
        "contacts_cache_bytes": contacts_info.get("bytes"),
        "contacts_cache_age_seconds": contacts_info.get("age_seconds"),
        "live_db_exists": bool(live_info.get("exists")),
        "live_db_bytes": live_info.get("bytes"),
        "live_db_mtime_iso": live_info.get("mtime_iso"),
        "live_db_age_seconds": live_info.get("age_seconds"),
        "live_db_newer_than_cache": live_newer,
        "last_synced_at": last_synced_at,
        "last_sync_method": last_sync_method,
        "last_sync_age_seconds": last_sync_age_seconds,
        "refresh_policy": {
            "scheduled": False,
            "on_manual_sync": True,
            "on_app_launch": True,
            "summary": "When you open the app, and when you press Sync cache.",
        },
        "cache_sync_method": settings_store.get_settings().get("cache_sync_method"),
        "terminal_sync": terminal_sync_paths(),
        "python_sync": {
            "executable": str(exe) if exe else None,
            "app": str(app) if app else None,
            "fda_target": runtime_status().get("fda_target"),
        },
    }
    if live_info.get("error"):
        info["live_db_error"] = live_info["error"]
    return info
