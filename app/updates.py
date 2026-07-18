"""Check GitHub Releases for newer MessageManager builds."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from app.version import APP_VERSION, GITHUB_REPO

log = logging.getLogger("messagemanager.updates")

# Space-free path so Installer / shell quoting never breaks on "Application Support".
UPDATE_PKG_PATH = Path("/tmp/MessageManager-update.pkg")


def _parse_version(value: str) -> tuple[int, ...]:
    cleaned = (value or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", cleaned)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts[:4])


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    return _parse_version(candidate) > _parse_version(current)


def _ssl_context() -> ssl.SSLContext:
    """Use certifi CAs when available (python.org builds often lack system roots)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _urlopen(req: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())


def updates_dir() -> Path:
    """Private folder for update downloads — avoids macOS Downloads TCC prompts."""
    path = Path.home() / "Library" / "Application Support" / "MessageManager" / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def check_for_update(timeout: float = 6.0) -> dict[str, Any]:
    """Return latest GitHub release info compared to this build."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"MessageManager/{APP_VERSION}",
        },
    )
    try:
        with _urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "ok": False,
                "update_available": False,
                "current_version": APP_VERSION,
                "latest_version": None,
                "detail": (
                    "GitHub returned 404 for releases/latest. "
                    "If the repository is private, make it public (or publish a public release) "
                    "so MessageManager can check for updates without authentication."
                ),
            }
        return {
            "ok": False,
            "update_available": False,
            "current_version": APP_VERSION,
            "detail": f"GitHub returned HTTP {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "update_available": False,
            "current_version": APP_VERSION,
            "detail": str(exc),
        }

    tag = str(payload.get("tag_name") or "").strip()
    latest = tag.lstrip("vV") or None
    assets = []
    for asset in payload.get("assets") or []:
        name = asset.get("name") or ""
        download = asset.get("browser_download_url") or ""
        if not download:
            continue
        lower = name.lower()
        kind = "other"
        if lower.endswith(".pkg"):
            kind = "pkg"
        elif lower.endswith(".dmg"):
            kind = "dmg"
        elif lower.endswith(".zip"):
            kind = "zip"
        assets.append({"name": name, "url": download, "kind": kind})

    preferred = next((a for a in assets if a["kind"] == "pkg"), None)
    if not preferred:
        preferred = next((a for a in assets if a["kind"] in {"dmg", "zip"}), None)

    update_available = bool(latest and is_newer(latest, APP_VERSION))
    return {
        "ok": True,
        "update_available": update_available,
        "current_version": APP_VERSION,
        "latest_version": latest,
        "release_name": payload.get("name") or tag,
        "release_notes": payload.get("body") or "",
        "html_url": payload.get("html_url"),
        "published_at": payload.get("published_at"),
        "assets": assets,
        "installer": preferred,
        "detail": None,
    }


def download_installer(url: str, dest_dir: Optional[str] = None) -> dict[str, Any]:
    """Download an installer asset (default: Application Support/updates)."""
    target_dir = Path(dest_dir).expanduser() if dest_dir else updates_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    name = url.rstrip("/").split("/")[-1] or "MessageManager-update.pkg"
    if not name.lower().endswith(".pkg"):
        name = "MessageManager-update.pkg"
    dest = target_dir / name

    for stale in target_dir.glob("MessageManager*.pkg"):
        try:
            if stale.resolve() != dest.resolve():
                stale.unlink(missing_ok=True)
        except OSError:
            pass

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"MessageManager/{APP_VERSION}"},
    )
    try:
        with _urlopen(req, timeout=120) as resp, dest.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc), "path": None}

    return {"ok": True, "path": str(dest), "detail": None}


def open_installer(pkg_path: str) -> dict[str, Any]:
    """Stage the pkg at /tmp and open it with Installer.app.

    The 1.0.30 detached ``osascript`` + ``installer`` path failed in practice
    (auth from a background script / paths with spaces) and left the app quit
    with a “cancelled or failed” notification. Opening Installer.app is reliable;
    using /tmp avoids Downloads TCC prompts.
    """
    src = Path(pkg_path).expanduser()
    if not src.is_file():
        return {"ok": False, "detail": f"Installer not found: {src}", "path": None}

    try:
        shutil.copy2(src, UPDATE_PKG_PATH)
        # Best-effort: drop the Application Support copy; /tmp is what Installer uses.
        try:
            if src.resolve() != UPDATE_PKG_PATH.resolve():
                src.unlink(missing_ok=True)
        except OSError:
            pass
    except OSError as exc:
        return {"ok": False, "detail": f"Could not stage installer: {exc}", "path": None}

    try:
        subprocess.Popen(  # noqa: S603
            ["open", str(UPDATE_PKG_PATH)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
    except OSError as exc:
        return {"ok": False, "detail": str(exc), "path": str(UPDATE_PKG_PATH)}

    log.info("Opened installer %s", UPDATE_PKG_PATH)
    return {"ok": True, "path": str(UPDATE_PKG_PATH), "detail": None}


# Back-compat alias for any older call sites.
def schedule_privileged_install(pkg_path: str) -> dict[str, Any]:
    return open_installer(pkg_path)
