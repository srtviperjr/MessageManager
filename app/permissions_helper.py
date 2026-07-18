"""Locate and run the Full Disk Access grant helper script."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from app.runtime_info import runtime_status
from app.version import BUNDLE_ID

FDA_URL = (
    "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension"
    "?Privacy_AllFiles"
)


def _repo_scripts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "scripts" / "macos"


def grant_script_paths() -> dict[str, Optional[str]]:
    base = _repo_scripts_dir()
    sh = base / "grant-full-disk-access.sh"
    command = base / "grant-full-disk-access.command"
    return {
        "script": str(sh) if sh.is_file() else None,
        "command": str(command) if command.is_file() else None,
        "dir": str(base) if base.is_dir() else None,
    }


def _app_bundle() -> Optional[Path]:
    apps = Path("/Applications/MessageManager.app")
    if apps.is_dir():
        return apps
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name.endswith(".app"):
            return parent
        if parent.name == "Contents" and parent.parent.name.endswith(".app"):
            return parent.parent
    return None


def _python_app_target() -> Optional[Path]:
    runtime = runtime_status()
    raw = runtime.get("fda_target")
    if raw:
        path = Path(str(raw))
        if path.is_dir() and path.name.endswith(".app"):
            return path
        # Neighboring Python.app from a bare binary path
        for parent in path.parents:
            if parent.name == "Python.app":
                return parent
    from app.cache_refresh import _framework_python_apps

    apps = _framework_python_apps()
    return apps[0] if apps else None


def _write_downloadable_command(
    script: Path,
    *,
    app: Optional[Path],
    fda_target: Optional[str],
) -> Optional[str]:
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    dest = downloads / "MessageManager-grant-full-disk-access.command"
    script_body = script.read_text(encoding="utf-8")
    if script_body.startswith("#!"):
        script_body = "\n".join(script_body.splitlines()[1:])
    lines = [
        "#!/bin/bash",
        "export KEEP_TERMINAL_OPEN=1",
        f'export MESSAGEMANAGER_BUNDLE_ID="{BUNDLE_ID}"',
    ]
    if app is not None:
        lines.append(f'export MESSAGEMANAGER_APP="{app}"')
    if fda_target:
        lines.append(f'export MESSAGEMANAGER_FDA_TARGET="{fda_target}"')
    dest.write_text("\n".join(lines) + "\n" + script_body + "\n", encoding="utf-8")
    dest.chmod(dest.stat().st_mode | 0o111)
    try:
        subprocess.Popen(["open", "-R", str(dest)])  # noqa: S603
    except OSError:
        pass
    return str(dest)


def _open_fda_settings() -> bool:
    try:
        subprocess.Popen(["open", FDA_URL])  # noqa: S603
        return True
    except OSError:
        try:
            subprocess.Popen(  # noqa: S603
                ["open", "/System/Library/PreferencePanes/Security.prefPane"]
            )
            return True
        except OSError:
            return False


def _reveal(path: Path) -> bool:
    try:
        subprocess.Popen(["open", "-R", str(path)])  # noqa: S603
        return True
    except OSError:
        return False


def register_fda_targets() -> dict[str, Any]:
    """
    Briefly probe MessageManager.app and Python.app so they appear in the
    Full Disk Access list (macOS often only lists apps that have attempted access).
    """
    from app.fda_probe import probe_app, probe_python

    app_result = probe_app()
    python_result = probe_python()
    return {
        "app": app_result,
        "python": python_result,
    }


def prepare_fda_grant(*, open_terminal: bool = False) -> dict[str, Any]:
    """
    Preferred grant flow: register app + Python with TCC, open Full Disk Access,
    reveal the exact bundles to enable. Terminal helper is optional.
    """
    app = _app_bundle()
    python_app = _python_app_target()
    registered = register_fda_targets()

    opened_settings = _open_fda_settings()
    revealed: list[str] = []
    if app is not None and app.exists() and _reveal(app):
        revealed.append(str(app))
    if python_app is not None and python_app.exists() and _reveal(python_app):
        revealed.append(str(python_app))

    steps = [
        "In Full Disk Access, click + if the apps are missing and add the ones Finder revealed.",
        "Turn ON MessageManager.",
        "Turn ON Python (Python.app from python.org — not Terminal, not a bare python3).",
        "If a switch is already on, turn it OFF then ON.",
        "Return here → Retest → Sync cache with Python.app.",
        "For MessageManager.app FDA to apply to launch-time cache copy: Quit MessageManager fully, then reopen.",
    ]

    terminal_launched = False
    exported: Optional[str] = None
    paths = grant_script_paths()
    script = Path(paths["script"]) if paths.get("script") else None
    if open_terminal and script is not None and script.is_file():
        # Optional: also run the shell helper for users who want Terminal instructions.
        try:
            result = run_grant_script(open_terminal=True, register=False)
            terminal_launched = bool(result.get("terminal_launched"))
            exported = result.get("exported")
        except (FileNotFoundError, OSError):
            pass

    return {
        "ok": True,
        "opened_settings": opened_settings,
        "terminal_launched": terminal_launched,
        "revealed": revealed,
        "registered": registered,
        "app_path": str(app) if app else None,
        "python_app": str(python_app) if python_app else None,
        "exported": exported,
        "steps": steps,
        "detail": (
            "Enable MessageManager and Python.app in Full Disk Access, then Retest. "
            "Terminal is only a workaround — not required when Python.app is enabled."
        ),
    }


def run_grant_script(
    *,
    open_terminal: bool = False,
    register: bool = True,
) -> dict[str, Any]:
    """
    Open Full Disk Access settings, reveal targets, optionally launch the
    helper script in Terminal, and save a copy to Downloads.
    """
    paths = grant_script_paths()
    script = Path(paths["script"]) if paths.get("script") else None
    command = Path(paths["command"]) if paths.get("command") else None
    if script is None or not script.is_file():
        raise FileNotFoundError("grant-full-disk-access.sh not found in the app bundle")

    try:
        script.chmod(script.stat().st_mode | 0o111)
        if command is not None and command.is_file():
            command.chmod(command.stat().st_mode | 0o111)
    except OSError:
        pass

    registered: Optional[dict[str, Any]] = None
    if register:
        try:
            registered = register_fda_targets()
        except Exception:  # noqa: BLE001
            registered = None

    app = _app_bundle()
    python_app = _python_app_target()
    fda_target = str(python_app) if python_app else runtime_status().get("fda_target")
    env = os.environ.copy()
    env["MESSAGEMANAGER_BUNDLE_ID"] = BUNDLE_ID
    if app is not None:
        env["MESSAGEMANAGER_APP"] = str(app)
    if fda_target:
        env["MESSAGEMANAGER_FDA_TARGET"] = str(fda_target)

    opened_settings = _open_fda_settings()

    revealed: list[str] = []
    if app is not None and app.exists() and _reveal(app):
        revealed.append(str(app))
    if fda_target and Path(fda_target).exists() and _reveal(Path(fda_target)):
        revealed.append(str(fda_target))

    terminal_launched = False
    launch_path = command if command is not None and command.is_file() else script
    if open_terminal and launch_path is not None:
        try:
            subprocess.Popen(  # noqa: S603
                ["open", "-a", "Terminal", str(launch_path)],
                env=env,
            )
            terminal_launched = True
        except OSError:
            try:
                subprocess.Popen(  # noqa: S603
                    ["/bin/bash", str(script)],
                    env=env,
                    start_new_session=True,
                )
                terminal_launched = True
            except OSError:
                terminal_launched = False

    exported: Optional[str] = None
    try:
        exported = _write_downloadable_command(
            script, app=app, fda_target=str(fda_target) if fda_target else None
        )
    except OSError:
        try:
            downloads = Path.home() / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            dest = downloads / "MessageManager-grant-full-disk-access.sh"
            shutil.copy2(script, dest)
            exported = str(dest)
        except OSError:
            exported = None

    return {
        "ok": True,
        "opened_settings": opened_settings,
        "terminal_launched": terminal_launched,
        "revealed": revealed,
        "registered": registered,
        "script": str(script),
        "exported": exported,
        "fda_target": fda_target,
        "app_path": str(app) if app else None,
        "python_app": str(python_app) if python_app else None,
        "detail": (
            "Enable MessageManager and Python.app in Full Disk Access, then Retest. "
            "Quit and reopen MessageManager after enabling the app toggle."
        ),
    }
