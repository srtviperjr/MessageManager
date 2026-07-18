"""Probe whether MessageManager / Python / Terminal can read Messages (FDA)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from app.cache_refresh import (
    _app_support,
    _find_macos_binary,
    _framework_python_launcher,
    _install_sync_helpers,
)
from app.logging_util import get_logger, log_dir
from app.runtime_info import runtime_status

log = get_logger("messagemanager.fda")

LIVE_DB = Path.home() / "Library" / "Messages" / "chat.db"
PROBE_DIR = log_dir()


def _probe_result_path(name: str) -> Path:
    return PROBE_DIR / f"fda-probe-{name}.json"


def _write_probe(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    path = _probe_result_path(name)
    data = dict(payload)
    data["id"] = name
    data["tested_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _try_read_messages_db() -> tuple[bool, str]:
    """Current process probe (usually the app venv — often fails on Tahoe)."""
    try:
        if not LIVE_DB.is_file():
            return False, f"Messages DB not found at {LIVE_DB}"
        with LIVE_DB.open("rb") as handle:
            handle.read(1)
        return True, "Readable"
    except PermissionError:
        return False, "Permission denied (no Full Disk Access for this process)"
    except OSError as exc:
        return False, str(exc)


def probe_server() -> dict[str, Any]:
    ok, detail = _try_read_messages_db()
    if ok:
        note = "Readable (unusual — venv normally uses the local cache)"
    else:
        note = (
            "Expected without live FDA — enable Python.app, then Sync cache. "
            "The server reads the local cache, not live Messages."
        )
        if detail:
            note = f"{note} ({detail})"
    return _write_probe(
        "server",
        {
            "label": "MessageManager server (venv — uses cache)",
            "ok": ok,
            "detail": note,
            "path": str(Path(__import__("sys").executable)),
            "informational": True,
        },
    )


def probe_python() -> dict[str, Any]:
    _script, _cmd = _install_sync_helpers()
    exe, app = _framework_python_launcher()
    runtime = runtime_status()
    if exe is None:
        return _write_probe(
            "python",
            {
                "label": "Python.app",
                "ok": False,
                "detail": (
                    "python.org Python.app not found. Install Python from "
                    "https://www.python.org/downloads/macos/ then Prepare FDA again."
                ),
                "path": runtime.get("fda_target"),
            },
        )

    out_path = _probe_result_path("python-child")
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass

    child = f"""
import json, sys
from pathlib import Path
p = Path.home() / "Library" / "Messages" / "chat.db"
out = Path({str(out_path)!r})
try:
    with p.open("rb") as f:
        f.read(1)
    out.write_text(json.dumps({{"ok": True, "detail": "Readable"}}), encoding="utf-8")
    sys.exit(0)
except PermissionError:
    out.write_text(json.dumps({{"ok": False, "detail": "Permission denied"}}), encoding="utf-8")
    sys.exit(2)
except Exception as e:
    out.write_text(json.dumps({{"ok": False, "detail": str(e)}}), encoding="utf-8")
    sys.exit(3)
"""
    try:
        completed = subprocess.run(  # noqa: S603
            [str(exe), "-c", child],
            capture_output=True,
            text=True,
            timeout=20,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _write_probe(
            "python",
            {
                "label": "Python.app",
                "ok": False,
                "detail": f"Probe failed to launch: {exc}",
                "path": str(app or exe),
            },
        )

    ok = False
    detail = f"Exit {completed.returncode}"
    if out_path.is_file():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            ok = bool(data.get("ok"))
            detail = str(data.get("detail") or detail)
        except (OSError, json.JSONDecodeError):
            pass
    elif completed.returncode == 0:
        ok = True
        detail = "Readable"
    elif completed.returncode == 2:
        detail = "Permission denied"

    return _write_probe(
        "python",
        {
            "label": "Python.app",
            "ok": ok,
            "detail": detail,
            "path": str(app or exe),
            "executable": str(exe),
        },
    )


def probe_app() -> dict[str, Any]:
    binary = _find_macos_binary()
    if binary is None:
        return _write_probe(
            "app",
            {
                "label": "MessageManager.app",
                "ok": False,
                "detail": "App binary not found",
                "path": "/Applications/MessageManager.app",
            },
        )

    out_path = _probe_result_path("app-child")
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass

    try:
        completed = subprocess.run(  # noqa: S603
            [str(binary), "--probe-fda", str(out_path)],
            capture_output=True,
            text=True,
            timeout=25,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _write_probe(
            "app",
            {
                "label": "MessageManager.app",
                "ok": False,
                "detail": f"Probe failed to launch: {exc}",
                "path": str(binary.parent.parent.parent),
            },
        )

    ok = False
    detail = f"Exit {completed.returncode}"
    if out_path.is_file():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            ok = bool(data.get("ok"))
            detail = str(data.get("detail") or detail)
        except (OSError, json.JSONDecodeError):
            pass
    elif completed.returncode == 0:
        ok = True
        detail = "Readable"
    elif completed.returncode == 2:
        detail = "Permission denied"

    note = detail
    if ok:
        note = f"{detail} — used for launch-time cache copy"
    else:
        note = (
            f"{detail}. Launch-time cache copy needs this; "
            "manual Sync uses Python.app instead."
        )
    return _write_probe(
        "app",
        {
            "label": "MessageManager.app (launch copy)",
            "ok": ok,
            "detail": note,
            "path": str(binary.parent.parent.parent),
            "informational": True,
        },
    )


def probe_terminal() -> dict[str, Any]:
    """
    Ask Terminal.app to run a short read probe (inherits Terminal FDA).
    """
    out_path = _probe_result_path("terminal-child")
    try:
        if out_path.exists():
            out_path.unlink()
    except OSError:
        pass

    dest_dir = _app_support() / "bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    probe_py = dest_dir / "fda-probe-terminal.py"
    probe_cmd = dest_dir / "fda-probe-terminal.command"
    probe_py.write_text(
        "import json\n"
        "from pathlib import Path\n"
        f"out = Path({str(out_path)!r})\n"
        "p = Path.home() / 'Library' / 'Messages' / 'chat.db'\n"
        "try:\n"
        "    with p.open('rb') as handle:\n"
        "        handle.read(1)\n"
        "    out.write_text(json.dumps({'ok': True, 'detail': 'Readable'}), encoding='utf-8')\n"
        "except PermissionError:\n"
        "    out.write_text(json.dumps({'ok': False, 'detail': 'Permission denied'}), encoding='utf-8')\n"
        "except Exception as exc:\n"
        "    out.write_text(json.dumps({'ok': False, 'detail': str(exc)}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    probe_cmd.write_text(
        "#!/bin/bash\n"
        f'exec /usr/bin/env python3 "{probe_py}"\n',
        encoding="utf-8",
    )
    try:
        probe_cmd.chmod(probe_cmd.stat().st_mode | 0o111)
    except OSError:
        pass

    try:
        subprocess.Popen(  # noqa: S603
            ["open", "-a", "Terminal", str(probe_cmd)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return _write_probe(
            "terminal",
            {
                "label": "Terminal.app",
                "ok": False,
                "detail": f"Could not open Terminal: {exc}",
                "path": "/System/Applications/Utilities/Terminal.app",
            },
        )

    deadline = time.monotonic() + 18
    while time.monotonic() < deadline:
        if out_path.is_file():
            try:
                data = json.loads(out_path.read_text(encoding="utf-8"))
                return _write_probe(
                    "terminal",
                    {
                        "label": "Terminal.app",
                        "ok": bool(data.get("ok")),
                        "detail": str(data.get("detail") or "Checked"),
                        "path": "/System/Applications/Utilities/Terminal.app",
                    },
                )
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(0.35)

    return _write_probe(
        "terminal",
        {
            "label": "Terminal.app",
            "ok": False,
            "detail": "No response — enable FDA for Terminal, quit Terminal, reopen, and retest",
            "path": "/System/Applications/Utilities/Terminal.app",
            "pending": True,
        },
    )


def probe_all(*, include_terminal: bool = True) -> dict[str, Any]:
    targets = [
        probe_app(),
        probe_python(),
        probe_server(),
    ]
    if include_terminal:
        targets.append(probe_terminal())

    # Sync methods only: Python.app preferred; Terminal as workaround.
    preferred_order = ("python", "terminal")
    recommended = next(
        (
            tid
            for tid in preferred_order
            for t in targets
            if t.get("id") == tid and t.get("ok")
        ),
        None,
    )
    python_ok = any(t.get("id") == "python" and t.get("ok") for t in targets)
    app_ok = any(t.get("id") == "app" and t.get("ok") for t in targets)
    return {
        "ok": True,
        "live_db": str(LIVE_DB),
        "targets": targets,
        "summary": {
            "any_ok": any(
                t.get("ok") for t in targets if t.get("id") in preferred_order
            ),
            "python_ok": python_ok,
            "app_ok": app_ok,
            "recommended": recommended,
            "clean_path_ready": python_ok,
            "guidance": (
                "Python.app can read Messages — use Sync cache (Python.app)."
                if python_ok
                else (
                    "Enable Full Disk Access for Python.app (Prepare FDA), then Retest "
                    "and Sync cache. Terminal is a workaround only."
                )
            ),
        },
    }
