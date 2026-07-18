"""Access / runtime diagnostics for troubleshooting Full Disk Access issues."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app import categories as categories_store
from app.contacts import contacts_status
from app.imessage import CHAT_DB, MESSAGES_DIR, access_status
from app.logging_util import log_dir
from app.logs_api import read_log_file
from app.platform_info import platform_status
from app.runtime_info import runtime_status
from app.version import APP_NAME, APP_VERSION, BUNDLE_ID, GITHUB_REPO


def _probe_path(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(path),
        "exists": False,
        "is_file": False,
        "is_dir": False,
        "readable": False,
        "size": None,
        "modified_at": None,
        "error": None,
    }
    try:
        info["exists"] = path.exists()
        if not info["exists"]:
            return info
        info["is_file"] = path.is_file()
        info["is_dir"] = path.is_dir()
        if info["is_file"]:
            stat = path.stat()
            info["size"] = stat.st_size
            info["modified_at"] = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()
            with path.open("rb") as handle:
                handle.read(1)
            info["readable"] = True
        elif info["is_dir"]:
            # Directory listing is enough to prove access.
            next(path.iterdir(), None)
            info["readable"] = True
    except PermissionError as exc:
        info["error"] = f"Permission denied: {exc}"
    except OSError as exc:
        info["error"] = str(exc)
    return info


def _app_support_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "MessageManager"


def _messages_cache_dir() -> Path:
    raw = (os.environ.get("THREAD_LEDGER_MESSAGES_CACHE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _app_support_root() / "messages-cache"


def _contacts_cache_dir() -> Path:
    raw = (os.environ.get("THREAD_LEDGER_CONTACTS_CACHE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _app_support_root() / "contacts-cache"


def _bundle_path() -> Optional[str]:
    # When running from the packaged app, Resources/app is under the .app bundle.
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name.endswith(".app"):
            return str(parent)
        macos = parent / "MacOS" / "MessageManager"
        if macos.is_file() and (parent.parent.name.endswith(".app") or parent.name == "Contents"):
            # .../MessageManager.app/Contents
            if parent.name == "Contents":
                return str(parent.parent)
    apps = Path("/Applications/MessageManager.app")
    if apps.is_dir():
        return str(apps)
    return None


def _short_path(path: Optional[str]) -> str:
    if not path:
        return ""
    name = Path(path).name
    if name.endswith(".app"):
        return name
    parent = Path(path).parent.name
    return f"{parent}/{name}" if parent else name


def _checklist(messages: dict[str, Any], runtime: dict[str, Any]) -> list[dict[str, Any]]:
    cache = _probe_path(_messages_cache_dir() / "chat.db")
    live = _probe_path(CHAT_DB)
    bundle = _bundle_path()
    python_exe = runtime.get("python_executable") or runtime.get("executable")
    fda_target = runtime.get("fda_target")
    fda_name = runtime.get("fda_target_name") or _short_path(fda_target) or "Python"
    items = [
        {
            "id": "app_installed",
            "label": "App installed",
            "ok": bool(bundle),
            "detail": "In /Applications" if bundle else "Install to /Applications",
        },
        {
            "id": "live_db_exists",
            "label": "Messages DB found",
            "ok": bool(live.get("exists")) or bool(cache.get("exists")),
            "detail": (
                "Found"
                if live.get("exists") or cache.get("exists")
                else "Open Messages once, then relaunch"
            ),
        },
        {
            "id": "cache_present",
            "label": "Launcher cache",
            "ok": bool(cache.get("exists")),
            "detail": (
                "Ready"
                if cache.get("exists")
                else "Missing — grant FDA to MessageManager.app"
            ),
        },
        {
            "id": "cache_readable",
            "label": "Readable by server",
            "ok": bool(messages.get("readable")),
            "detail": "OK" if messages.get("readable") else "Permission denied",
        },
        {
            "id": "python_runtime",
            "label": "Python runtime",
            "ok": bool(python_exe),
            "detail": _short_path(python_exe) or "Unknown",
        },
        {
            "id": "fda_targets",
            "label": "Enable in Full Disk Access",
            "ok": bool(messages.get("readable")),
            "detail": (
                f"MessageManager.app + {fda_name}"
                if fda_target
                else "MessageManager.app"
            ),
        },
    ]
    return items


def build_diagnostics() -> dict[str, Any]:
    messages = access_status()
    contacts = contacts_status(quick=False)
    runtime = runtime_status()
    cache_dir = _messages_cache_dir()
    contacts_cache = _contacts_cache_dir()
    support = _app_support_root()

    probes = {
        "messages_live_dir": _probe_path(MESSAGES_DIR),
        "messages_live_db": _probe_path(CHAT_DB),
        "messages_cache_dir": _probe_path(cache_dir),
        "messages_cache_db": _probe_path(cache_dir / "chat.db"),
        "contacts_cache_dir": _probe_path(contacts_cache),
        "app_support": _probe_path(support),
        "log_dir": _probe_path(log_dir()),
    }

    env = {
        key: os.environ.get(key)
        for key in (
            "THREAD_LEDGER_DATA",
            "THREAD_LEDGER_MESSAGES_CACHE",
            "THREAD_LEDGER_CONTACTS_CACHE",
            "THREAD_LEDGER_MANAGED",
        )
    }

    log_tails: dict[str, Any] = {}
    for name in ("launch.log", "app.log", "server.log", "install.log"):
        try:
            log_tails[name] = read_log_file(name, tail_lines=120)
        except (FileNotFoundError, ValueError, OSError) as exc:
            log_tails[name] = {"name": name, "error": str(exc), "content": ""}

    checklist = _checklist(messages, runtime)
    next_steps: list[str] = []
    if not messages.get("readable"):
        next_steps.append(
            "Run the grant script or open Privacy Settings, enable MessageManager.app, quit, reopen."
        )
        if runtime.get("fda_target"):
            next_steps.append(
                f"Also enable: {_short_path(runtime.get('fda_target'))}."
            )
        if not probes["messages_live_db"].get("exists") and not probes[
            "messages_cache_db"
        ].get("exists"):
            next_steps.append("Open the Messages app once, then relaunch.")
        next_steps.append("If stuck, export a support bundle from Logs.")
    else:
        next_steps.append("Messages access looks OK.")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "bundle_id": BUNDLE_ID,
            "github_repo": GITHUB_REPO,
            "bundle_path": _bundle_path(),
        },
        "platform": {
            **platform_status(),
            "mac_ver": platform.mac_ver(),
            "python_version": platform.python_version(),
            "machine": platform.machine(),
            "node": platform.node(),
        },
        "runtime": runtime,
        "messages": messages,
        "contacts": contacts,
        "categories": categories_store.status(),
        "probes": probes,
        "env": env,
        "checklist": checklist,
        "next_steps": next_steps,
        "log_tails": {
            name: {
                "path": payload.get("path"),
                "error": payload.get("error"),
                "truncated": payload.get("truncated"),
                "returned_lines": payload.get("returned_lines"),
                "content": payload.get("content") or "",
            }
            for name, payload in log_tails.items()
        },
        "summary": _human_summary(messages, contacts, checklist, next_steps, runtime),
    }


def _human_summary(
    messages: dict[str, Any],
    contacts: dict[str, Any],
    checklist: list[dict[str, Any]],
    next_steps: list[str],
    runtime: dict[str, Any],
) -> str:
    lines = [
        f"{APP_NAME} {APP_VERSION} diagnostics",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Checklist:",
    ]
    for item in checklist:
        mark = "OK" if item.get("ok") else "FAIL"
        lines.append(f"- [{mark}] {item.get('label')}: {item.get('detail')}")
    lines.extend(
        [
            "",
            f"Messages readable: {messages.get('readable')}",
            f"Messages using_cache: {messages.get('using_cache')}",
            f"Messages error: {messages.get('error') or '(none)'}",
            f"Contacts available: {contacts.get('available')} (keys={contacts.get('contact_keys')})",
            f"Contacts error: {contacts.get('error') or '(none)'}",
            f"Python: {runtime.get('executable')}",
            f"FDA target: {runtime.get('fda_target')}",
            "",
            "Next steps:",
        ]
    )
    for step in next_steps:
        lines.append(f"- {step}")
    return "\n".join(lines)


def format_support_bundle(report: Optional[dict[str, Any]] = None) -> str:
    """Plain-text bundle suitable for pasting into chat/email."""
    data = report or build_diagnostics()
    parts = [
        data.get("summary") or "",
        "",
        "=" * 72,
        "FULL JSON REPORT",
        "=" * 72,
        json.dumps(
            {
                key: value
                for key, value in data.items()
                if key != "log_tails"
            },
            indent=2,
            default=str,
        ),
        "",
    ]
    for name in ("launch.log", "app.log", "server.log", "install.log"):
        payload = (data.get("log_tails") or {}).get(name) or {}
        parts.append("=" * 72)
        parts.append(f"LOG TAIL: {name}")
        if payload.get("path"):
            parts.append(payload["path"])
        if payload.get("error"):
            parts.append(f"(error: {payload['error']})")
        parts.append("=" * 72)
        parts.append(payload.get("content") or "(empty / missing)")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def export_support_bundle() -> dict[str, Any]:
    """Write support bundle to Downloads and reveal it in Finder."""
    text = format_support_bundle()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    dest = downloads / f"MessageManager-support-{stamp}.txt"
    dest.write_text(text, encoding="utf-8")
    try:
        subprocess.Popen(["open", "-R", str(dest)])  # noqa: S603
    except OSError:
        pass
    return {
        "ok": True,
        "path": str(dest),
        "bytes": dest.stat().st_size,
        "detail": "Support bundle saved to Downloads",
    }
