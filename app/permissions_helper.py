"""Locate and run the Full Disk Access grant helper script."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from app.runtime_info import runtime_status
from app.version import BUNDLE_ID


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


def run_grant_script(*, open_terminal: bool = True) -> dict[str, Any]:
    """
    Open Full Disk Access settings, reveal targets, and optionally launch the
    helper script in Terminal so the user sees step-by-step instructions.
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

    runtime = runtime_status()
    app = _app_bundle()
    fda_target = runtime.get("fda_target")
    env = os.environ.copy()
    env["MESSAGEMANAGER_BUNDLE_ID"] = BUNDLE_ID
    if app is not None:
        env["MESSAGEMANAGER_APP"] = str(app)
    if fda_target:
        env["MESSAGEMANAGER_FDA_TARGET"] = str(fda_target)

    fda_url = (
        "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension"
        "?Privacy_AllFiles"
    )
    opened_settings = False
    try:
        subprocess.Popen(["open", fda_url], env=env)  # noqa: S603
        opened_settings = True
    except OSError:
        try:
            subprocess.Popen(  # noqa: S603
                ["open", "/System/Library/PreferencePanes/Security.prefPane"],
                env=env,
            )
            opened_settings = True
        except OSError:
            opened_settings = False

    revealed: list[str] = []
    if app is not None and app.exists():
        try:
            subprocess.Popen(["open", "-R", str(app)], env=env)  # noqa: S603
            revealed.append(str(app))
        except OSError:
            pass
    if fda_target and Path(fda_target).exists():
        try:
            subprocess.Popen(["open", "-R", str(fda_target)], env=env)  # noqa: S603
            revealed.append(str(fda_target))
        except OSError:
            pass

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
            script, app=app, fda_target=fda_target
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
        "script": str(script),
        "exported": exported,
        "fda_target": fda_target,
        "detail": (
            "Opened Full Disk Access. Enable MessageManager, then quit and reopen."
        ),
    }
