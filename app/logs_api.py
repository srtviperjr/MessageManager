"""Read MessageManager log files for the in-app viewer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.logging_util import log_dir

ALLOWED_LOGS = {
    "app.log",
    "launch.log",
    "server.log",
    "install.log",
}


def list_log_files() -> dict[str, Any]:
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.log")):
        if path.name not in ALLOWED_LOGS and not path.name.endswith(".log"):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        files.append(
            {
                "name": path.name,
                "path": str(path),
                "size": stat.st_size,
                "modified_at": mtime,
            }
        )
    # Prefer common logs first even if empty / missing from glob order.
    order = {name: idx for idx, name in enumerate(["launch.log", "app.log", "server.log", "install.log"])}
    files.sort(key=lambda item: (order.get(item["name"], 99), item["name"]))
    return {"log_dir": str(directory), "files": files}


def read_log_file(name: str, *, tail_lines: int = 400) -> dict[str, Any]:
    safe = Path(name).name
    if safe != name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("Invalid log name")
    if not safe.endswith(".log"):
        raise ValueError("Only .log files can be viewed")

    path = log_dir() / safe
    if not path.is_file():
        raise FileNotFoundError(f"Log not found: {safe}")

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise OSError(f"Could not read {safe}: {exc}") from exc

    lines = text.splitlines()
    total = len(lines)
    limit = max(50, min(int(tail_lines or 400), 5000))
    clipped = lines[-limit:]
    return {
        "name": safe,
        "path": str(path),
        "total_lines": total,
        "returned_lines": len(clipped),
        "truncated": total > len(clipped),
        "content": "\n".join(clipped),
    }
