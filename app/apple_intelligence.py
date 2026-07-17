"""Apple Intelligence summarization via a Shortcuts bridge (Apple Silicon)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.platform_info import is_apple_silicon
from app.settings import get_settings

SHORTCUT_SETUP = (
    "Create a Shortcut named “{name}” that: "
    "1) receives Text input, "
    "2) runs Summarize (Apple Intelligence / Writing Tools), "
    "3) stops and returns the summary text. "
    "Then toggle Apple Intelligence on and try again."
)


class AppleIntelligenceError(Exception):
    """Raised when Apple Intelligence summarization cannot run."""


def shortcuts_cli_available() -> bool:
    return shutil.which("shortcuts") is not None


def list_shortcut_names() -> list[str]:
    if not shortcuts_cli_available():
        return []
    try:
        result = subprocess.run(
            ["shortcuts", "list"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def shortcut_installed(name: Optional[str] = None) -> bool:
    target = name or get_settings()["apple_intelligence_shortcut"]
    return target in list_shortcut_names()


def capability_status() -> dict[str, Any]:
    settings = get_settings()
    shortcut = settings["apple_intelligence_shortcut"]
    silicon = is_apple_silicon()
    cli = shortcuts_cli_available()
    installed = shortcut_installed(shortcut) if cli and silicon else False

    reasons: list[str] = []
    if not silicon:
        reasons.append("This Mac is not Apple Silicon (Apple Intelligence requires M1 or later).")
    if not cli:
        reasons.append("The macOS `shortcuts` CLI is not available.")
    elif silicon and not installed:
        reasons.append(SHORTCUT_SETUP.format(name=shortcut))

    available = bool(silicon and cli and installed)
    return {
        "apple_silicon": silicon,
        "shortcuts_cli": cli,
        "shortcut_name": shortcut,
        "shortcut_installed": installed,
        "available": available,
        "enabled": bool(settings["apple_intelligence_enabled"]),
        "reasons": reasons,
        "setup_hint": SHORTCUT_SETUP.format(name=shortcut),
    }


def format_thread_for_summary(thread: dict[str, Any], *, max_messages: int = 120) -> str:
    name = thread.get("display_name") or "Conversation"
    messages = [m for m in thread.get("messages", []) if (m.get("text") or "").strip()]
    messages = messages[-max_messages:]
    lines = [
        f"Summarize the overall discussion in this iMessage conversation with {name}.",
        "",
        "Write 1–3 short paragraphs that explain:",
        "1) What the conversation is mainly about as a whole",
        "2) How the discussion developed (what it started on, what it moved to)",
        "3) Any decisions, agreements, disagreements, or open questions",
        "",
        "Focus on the broader context and narrative of the exchange.",
        "Do not list messages one by one. Do not quote every detail.",
        "Ignore links, reactions, and system noise unless they matter to the discussion.",
        "",
        "Messages (oldest first):",
    ]
    for msg in messages:
        who = (
            "Me"
            if msg.get("is_from_me")
            else (msg.get("sender_name") or msg.get("sender") or "Them")
        )
        text = " ".join(msg["text"].split())
        if len(text) > 500:
            text = text[:497] + "…"
        when = msg.get("sent_at") or ""
        prefix = f"[{when}] " if when else ""
        lines.append(f"{prefix}{who}: {text}")
    return "\n".join(lines)


def summarize_with_apple_intelligence(
    thread: dict[str, Any],
    *,
    max_messages: int = 120,
) -> dict[str, Any]:
    status = capability_status()
    if not status["apple_silicon"]:
        raise AppleIntelligenceError(
            "Apple Intelligence requires Apple Silicon (M1 or later). "
            "Turn off the Apple Intelligence toggle to use local extractive summaries."
        )
    if not status["shortcuts_cli"]:
        raise AppleIntelligenceError("macOS Shortcuts CLI is unavailable on this Mac.")
    if not status["shortcut_installed"]:
        raise AppleIntelligenceError(status["setup_hint"])

    prompt = format_thread_for_summary(thread, max_messages=max_messages)
    if len(prompt.strip().splitlines()) <= 4:
        raise AppleIntelligenceError("No text messages available to summarize in this thread.")

    shortcut = status["shortcut_name"]
    with tempfile.TemporaryDirectory(prefix="messagemanager-ai-") as tmp:
        in_path = Path(tmp) / "input.txt"
        out_path = Path(tmp) / "output.txt"
        in_path.write_text(prompt, encoding="utf-8")

        # Prefer file input/output so longer threads don't hit argv/stdin limits.
        cmd = [
            "shortcuts",
            "run",
            shortcut,
            "--input-path",
            str(in_path),
            "--output-path",
            str(out_path),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AppleIntelligenceError(
                "Apple Intelligence summary timed out. Try a shorter thread window."
            ) from exc
        except OSError as exc:
            raise AppleIntelligenceError(f"Could not run Shortcuts: {exc}") from exc

        summary = ""
        if out_path.exists():
            summary = out_path.read_text(encoding="utf-8", errors="replace").strip()
        if not summary:
            summary = (result.stdout or "").strip()

        if result.returncode != 0 and not summary:
            err = (result.stderr or result.stdout or "Unknown Shortcuts error").strip()
            raise AppleIntelligenceError(
                f"Shortcut “{shortcut}” failed: {err}. "
                "Confirm it accepts Text input and returns summarized text."
            )
        if not summary:
            raise AppleIntelligenceError(
                f"Shortcut “{shortcut}” returned no text. "
                "Make sure the final action outputs the summary."
            )

    messages = [m for m in thread.get("messages", []) if (m.get("text") or "").strip()][
        -max_messages:
    ]
    from_me = sum(1 for m in messages if m.get("is_from_me"))
    return {
        "summary": summary,
        "highlights": [],
        "topics": [],
        "stats": {
            "message_count": len(messages),
            "from_me": from_me,
            "from_them": len(messages) - from_me,
            "first_at": messages[0].get("sent_at") if messages else None,
            "last_at": messages[-1].get("sent_at") if messages else None,
        },
        "method": "apple_intelligence",
    }
