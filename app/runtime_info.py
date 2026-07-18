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


def _resources_python_app(bin_or_home: Path) -> Optional[Path]:
    """Resolve .../Versions/X.Y/Resources/Python.app from a bin/ or home path."""
    candidates = [
        bin_or_home / "Resources" / "Python.app",
        bin_or_home.parent / "Resources" / "Python.app",
        bin_or_home.parent.parent / "Resources" / "Python.app",
    ]
    for app in candidates:
        if app.is_dir():
            return app
    return None


def python_fda_target(executable: Optional[str] = None) -> Optional[str]:
    """Best path to add in Full Disk Access for the running interpreter."""
    exe = Path(executable or sys.executable).resolve()
    app = _python_app_from_path(exe)
    if app:
        return str(app)

    home = _venv_home(exe)
    if home:
        app = _python_app_from_path(home) or _resources_python_app(home)
        if app:
            return str(app)

    app = _resources_python_app(exe.parent)
    if app:
        return str(app)

    # Prefer python.org Framework Python.app when present — that is what the
    # packaged launcher should run after recreating the venv.
    for version in ("3.13", "3.12", "3.11", "3.10", "3.9"):
        preferred = Path(
            f"/Library/Frameworks/Python.framework/Versions/{version}/Resources/Python.app"
        )
        if preferred.is_dir():
            return str(preferred)

    if exe.exists():
        return str(exe)
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
