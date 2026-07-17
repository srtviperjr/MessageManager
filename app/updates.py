"""Check GitHub Releases for newer MessageManager builds."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from app.version import APP_VERSION, GITHUB_REPO


def _parse_version(value: str) -> tuple[int, ...]:
    cleaned = (value or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", cleaned)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts[:4])


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    return _parse_version(candidate) > _parse_version(current)


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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "ok": True,
                "update_available": False,
                "current_version": APP_VERSION,
                "latest_version": None,
                "detail": "No GitHub releases published yet.",
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
    """Download an installer asset to Downloads (or dest_dir)."""
    from pathlib import Path

    target_dir = Path(dest_dir).expanduser() if dest_dir else Path.home() / "Downloads"
    target_dir.mkdir(parents=True, exist_ok=True)
    name = url.rstrip("/").split("/")[-1] or "MessageManager-update.pkg"
    dest = target_dir / name

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"MessageManager/{APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc), "path": None}

    return {"ok": True, "path": str(dest), "detail": None}
