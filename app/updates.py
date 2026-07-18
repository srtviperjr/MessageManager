"""Check GitHub Releases for newer MessageManager builds."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from app.version import APP_VERSION, GITHUB_REPO

log = logging.getLogger("messagemanager.updates")


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
    """Private folder for update pkgs — avoids macOS Downloads TCC prompts."""
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
    """Download an installer asset to Application Support/updates (or dest_dir)."""
    target_dir = Path(dest_dir).expanduser() if dest_dir else updates_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    name = url.rstrip("/").split("/")[-1] or "MessageManager-update.pkg"
    # Keep a stable name so cleanup is predictable.
    if not name.lower().endswith(".pkg"):
        name = "MessageManager-update.pkg"
    dest = target_dir / name

    # Remove older update pkgs in this folder first (same permission domain).
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


def schedule_privileged_install(pkg_path: str) -> dict[str, Any]:
    """Install a downloaded .pkg with a single admin password, then exit.

    Avoids opening Installer.app against ~/Downloads (which triggered repeated
    Files and Folders prompts for Downloads + Applications). Uses the system
    ``installer`` tool once under administrator privileges. Postinstall still
    relaunches MessageManager after the package scripts finish.
    """
    pkg = Path(pkg_path).expanduser()
    if not pkg.is_file():
        return {"ok": False, "detail": f"Installer not found: {pkg}"}

    support = Path.home() / "Library" / "Application Support" / "MessageManager"
    helper_dir = support / "bin"
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper = helper_dir / "run-update-install.sh"
    log_path = support / "logs" / "update-install.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    pkg_q = shlex.quote(str(pkg))
    updates_q = shlex.quote(str(updates_dir()))
    log_q = shlex.quote(str(log_path))

    helper.write_text(
        f"""#!/bin/bash
set +e
PKG={pkg_q}
UPDATES={updates_q}
LOG={log_q}

log() {{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >>"$LOG" 2>/dev/null || true
}}

log "update helper starting for $PKG"

# Let the running app finish shutting down so the bundle can be replaced.
for _ in $(seq 1 60); do
  if ! pgrep -f "MessageManager.app/Contents/MacOS/MessageManager" >/dev/null 2>&1; then
    break
  fi
  /usr/bin/osascript -e 'tell application "MessageManager" to quit' >/dev/null 2>&1 || true
  sleep 0.5
done
sleep 0.3

# One admin password → install into /Applications. No Installer.app GUI and no
# ~/Downloads touch, so macOS should not re-prompt for Downloads/Applications.
log "requesting administrator privileges for installer"
/usr/bin/osascript -e "do shell script \\"/usr/sbin/installer -pkg $(printf %q "$PKG") -target /\\" with administrator privileges" >>"$LOG" 2>&1
STATUS=$?
log "installer exit status=$STATUS"

# Drop the private update pkg after the attempt (postinstall also cleans as root).
rm -f "$PKG" 2>/dev/null || true
rm -f "$UPDATES"/MessageManager*.pkg 2>/dev/null || true

if [[ "$STATUS" -ne 0 ]]; then
  log "install failed or cancelled"
  /usr/bin/osascript -e 'display notification "Update install was cancelled or failed. You can try again from Settings." with title "MessageManager"' >/dev/null 2>&1 || true
fi

# Relaunch is handled once by the pkg postinstall finish-install helper.
rm -f "$0" 2>/dev/null || true
log "update helper finished"
exit "$STATUS"
""",
        encoding="utf-8",
    )
    helper.chmod(helper.stat().st_mode | 0o755)

    try:
        subprocess.Popen(  # noqa: S603
            ["/bin/bash", str(helper)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}

    log.info("Scheduled privileged install via %s", helper)
    return {"ok": True, "path": str(pkg), "helper": str(helper), "detail": None}
