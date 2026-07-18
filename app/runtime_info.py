"""Runtime Python details for Full Disk Access guidance."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional


def _python_app_from_path(path: Path) -> Optional[Path]:
    parts = path.resolve().parts
    if "Python.app" in parts:
        idx = parts.index("Python.app")
        return Path(*parts[: idx + 1])
    return None


def _venv_home(executable: Path) -> Optional[Path]:
    """Return the base interpreter home for a venv executable, if any."""
    cfg = executable.resolve().parent.parent / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    try:
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("home"):
                _, _, value = line.partition("=")
                home = Path(value.strip())
                if home.exists():
                    return home
    except OSError:
        return None
    return None


def python_fda_target(executable: Optional[str] = None) -> Optional[str]:
    """Best path to add in Full Disk Access for the running interpreter."""
    exe = Path(executable or sys.executable)
    app = _python_app_from_path(exe)
    if app:
        return str(app)

    home = _venv_home(exe)
    if home:
        # home is typically .../bin — climb to Python.app if present
        app = _python_app_from_path(home)
        if app:
            return str(app)
        # Official python.org layout: .../Versions/3.x/bin -> Resources/Python.app
        resources_app = home.parent / "Resources" / "Python.app"
        if resources_app.is_dir():
            return str(resources_app)
        # CLT layout already handled via Python.app in path; fall back to home/python3
        candidate = home / "python3"
        if candidate.exists():
            return str(candidate)

    if exe.exists():
        return str(exe.resolve())
    return None


def runtime_status() -> dict[str, Any]:
    exe = str(Path(sys.executable).resolve())
    target = python_fda_target(exe)
    return {
        "python_executable": exe,
        "python_version": sys.version.split()[0],
        "fda_target": target,
        "fda_target_name": Path(target).name if target else None,
    }
