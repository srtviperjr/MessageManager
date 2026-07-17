"""Local web API for browsing, categorizing, and summarizing iMessage threads."""

from __future__ import annotations

import json
import os
import queue
import signal
import threading
import time
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import categories as categories_store
from app import settings as settings_store
from app.apple_intelligence import (
    AppleIntelligenceError,
    capability_status,
    summarize_with_apple_intelligence,
)
from app.contacts import contacts_status
from app.imessage import (
    MAX_THREAD_LIMIT,
    MessagesAccessError,
    access_status,
    count_threads,
    get_thread_messages,
    list_threads,
)
from app.logging_util import configure_logging, get_logger, log_dir, log_file_path
from app.platform_info import platform_status
from app.summarize import summarize_thread

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

configure_logging()
log = get_logger("messagemanager")

app = FastAPI(title="MessageManager", version="0.1.0")


class CategoryUpdate(BaseModel):
    category: Literal["business", "personal", "uncategorized"]
    chat_guid: Optional[str] = None
    notes: Optional[str] = None


class SummaryRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=3650)
    max_messages: int = Field(default=500, ge=10, le=2000)
    max_sentences: int = Field(default=5, ge=1, le=12)
    # None = follow saved settings toggle + platform capabilities
    use_apple_intelligence: Optional[bool] = None


class SettingsUpdate(BaseModel):
    apple_intelligence_enabled: Optional[bool] = None
    apple_intelligence_shortcut: Optional[str] = Field(default=None, min_length=1, max_length=200)
    summary_days: Optional[int] = Field(default=None, ge=1, le=3650)
    thread_limit: Optional[int] = Field(default=None, ge=5, le=MAX_THREAD_LIMIT)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _enrich_threads(
    threads: list[dict[str, Any]],
    category: Optional[str],
    q: Optional[str],
) -> dict[str, Any]:
    cats = categories_store.get_all()
    for thread in threads:
        info = cats.get(thread["id"])
        thread["category"] = info["category"] if info else "uncategorized"
        thread["notes"] = info.get("notes") if info else None

    counts = {"business": 0, "personal": 0, "uncategorized": 0}
    for t in threads:
        counts[t["category"]] = counts.get(t["category"], 0) + 1

    if category and category != "all":
        threads = [t for t in threads if t["category"] == category]

    if q:
        needle = q.lower().strip()
        threads = [
            t
            for t in threads
            if needle in (t.get("display_name") or "").lower()
            or needle in (t.get("chat_identifier") or "").lower()
            or needle in (t.get("preview") or "").lower()
            or any(needle in (p or "").lower() for p in t.get("participants") or [])
            or any(needle in (p or "").lower() for p in t.get("participant_names") or [])
        ]

    return {"threads": threads, "counts": counts, "total": len(threads)}


def _want_apple_intelligence(requested: Optional[bool]) -> bool:
    settings = settings_store.get_settings()
    return bool(settings["apple_intelligence_enabled"] if requested is None else requested)


def _require_apple_intelligence_ready() -> None:
    caps = capability_status()
    if not caps["apple_silicon"]:
        raise AppleIntelligenceError(
            "Apple Intelligence is on, but this Mac is not Apple Silicon (M1 or later)."
        )
    if not caps["available"]:
        raise AppleIntelligenceError(caps["setup_hint"])


def _build_summary(chat_id: int, req: SummaryRequest, progress=None) -> dict[str, Any]:
    thread = get_thread_messages(
        chat_id,
        limit=req.max_messages,
        days=req.days,
        progress=progress,
    )
    use_ai = _want_apple_intelligence(req.use_apple_intelligence)

    if progress:
        progress(
            "Running Apple Intelligence…" if use_ai else "Building extractive summary…",
            92,
        )

    if use_ai:
        _require_apple_intelligence_ready()
        try:
            result = summarize_with_apple_intelligence(
                thread,
                max_messages=req.max_messages,
            )
        except AppleIntelligenceError:
            log.exception(
                "Apple Intelligence summary failed for chat_id=%s days=%s",
                chat_id,
                req.days,
            )
            raise
    else:
        result = summarize_thread(
            thread,
            max_sentences=req.max_sentences,
            max_messages=req.max_messages,
        )

    result["chat_id"] = chat_id
    result["display_name"] = thread["display_name"]
    result["used_apple_intelligence"] = bool(use_ai)
    result["platform"] = platform_status()
    result["days"] = req.days
    result["message_count"] = len(thread.get("messages") or [])
    result["cutoff_at"] = thread.get("cutoff_at")
    if progress:
        progress("Summary ready", 100)
    return result


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "platform": platform_status(),
        "messages": access_status(),
        "contacts": contacts_status(quick=True),
        "apple_intelligence": capability_status(),
        "settings": settings_store.get_settings(),
        "logs": {
            "app_log": str(log_file_path()),
            "log_dir": str(log_dir()),
            "launch_log": str(log_dir() / "launch.log"),
        },
    }


@app.post("/api/shutdown")
def shutdown() -> dict:
    """Stop the local server (used by the macOS keep-alive window / Quit button)."""

    def _stop() -> None:
        time.sleep(0.25)
        log.info("Shutdown requested")
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_stop, daemon=True).start()
    return {"ok": True}


@app.get("/api/settings")
def api_get_settings() -> dict:
    return {
        "settings": settings_store.get_settings(),
        "apple_intelligence": capability_status(),
        "platform": platform_status(),
    }


@app.put("/api/settings")
def api_put_settings(body: SettingsUpdate) -> dict:
    patch = body.model_dump(exclude_none=True)
    if "apple_intelligence_shortcut" in patch:
        patch["apple_intelligence_shortcut"] = patch["apple_intelligence_shortcut"].strip()
        if not patch["apple_intelligence_shortcut"]:
            raise HTTPException(status_code=400, detail="Shortcut name cannot be empty.")
    if patch.get("apple_intelligence_enabled") and not platform_status()["apple_silicon"]:
        raise HTTPException(
            status_code=400,
            detail="Apple Intelligence requires Apple Silicon (M1 or later).",
        )
    updated = settings_store.update_settings(patch)
    return {
        "settings": updated,
        "apple_intelligence": capability_status(),
        "platform": platform_status(),
    }


@app.get("/api/threads/available")
def api_threads_available() -> dict:
    """Return how many conversations exist (for the load slider max)."""
    try:
        available = count_threads()
    except MessagesAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Failed to count threads")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"available_threads": available}


@app.get("/api/threads")
def api_threads(
    category: Optional[Literal["business", "personal", "uncategorized", "all"]] = Query("all"),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=MAX_THREAD_LIMIT),
) -> dict:
    try:
        threads, available = list_threads(limit=limit)
    except MessagesAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    payload = _enrich_threads(threads, category, q)
    payload["available_threads"] = available
    return payload


@app.get("/api/threads/stream")
def api_threads_stream(
    category: Optional[Literal["business", "personal", "uncategorized", "all"]] = Query("all"),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=MAX_THREAD_LIMIT),
) -> StreamingResponse:
    def generate():
        events: queue.Queue = queue.Queue()

        def progress(message: str, percent: int) -> None:
            events.put({"type": "progress", "message": message, "percent": percent})

        def worker() -> None:
            try:
                threads, available = list_threads(limit=limit, progress=progress)
                payload = _enrich_threads(threads, category, q)
                payload["available_threads"] = available
                events.put({"type": "result", **payload})
            except MessagesAccessError as exc:
                events.put({"type": "error", "detail": str(exc)})
            except Exception as exc:  # noqa: BLE001
                events.put({"type": "error", "detail": str(exc)})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        yield _sse({"type": "progress", "message": "Starting…", "percent": 1})
        while True:
            item = events.get()
            if item is None:
                break
            yield _sse(item)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.put("/api/threads/{chat_id}/category")
def api_set_category(chat_id: int, body: CategoryUpdate) -> dict:
    return categories_store.set_category(
        chat_id,
        body.category,
        chat_guid=body.chat_guid,
        notes=body.notes,
    )


@app.get("/api/threads/{chat_id}/messages")
def api_thread_messages(
    chat_id: int,
    limit: int = Query(10, ge=1, le=100),
) -> dict:
    """Return the most recent messages for a thread (chronological order)."""
    try:
        thread = get_thread_messages(chat_id, limit=limit, days=None)
        return {
            "id": thread["id"],
            "display_name": thread.get("display_name"),
            "messages": thread.get("messages") or [],
        }
    except MessagesAccessError as exc:
        log.warning("Messages access error: %s", exc)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Failed to load messages for chat_id=%s", chat_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/threads/{chat_id}/summary")
def api_summary(chat_id: int, body: Optional[SummaryRequest] = None) -> dict:
    req = body or SummaryRequest(days=settings_store.get_settings().get("summary_days", 30))
    try:
        return _build_summary(chat_id, req)
    except MessagesAccessError as exc:
        log.warning("Messages access error: %s", exc)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AppleIntelligenceError as exc:
        log.error("Apple Intelligence error: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Summary failed for chat_id=%s", chat_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/threads/{chat_id}/summary/stream")
def api_summary_stream(
    chat_id: int,
    days: int = Query(30, ge=1, le=3650),
    max_messages: int = Query(500, ge=10, le=2000),
    max_sentences: int = Query(5, ge=1, le=12),
    use_apple_intelligence: Optional[bool] = Query(None),
) -> StreamingResponse:
    req = SummaryRequest(
        days=days,
        max_messages=max_messages,
        max_sentences=max_sentences,
        use_apple_intelligence=use_apple_intelligence,
    )

    def generate():
        events: queue.Queue = queue.Queue()

        def progress(message: str, percent: int) -> None:
            events.put({"type": "progress", "message": message, "percent": percent})

        def worker() -> None:
            try:
                result = _build_summary(chat_id, req, progress=progress)
                events.put({"type": "result", "summary": result})
            except MessagesAccessError as exc:
                log.warning("Messages access error: %s", exc)
                events.put({"type": "error", "detail": str(exc)})
            except KeyError as exc:
                events.put({"type": "error", "detail": str(exc)})
            except AppleIntelligenceError as exc:
                log.error("Apple Intelligence error: %s", exc)
                events.put({"type": "error", "detail": str(exc)})
            except Exception as exc:  # noqa: BLE001
                log.exception("Summary stream failed for chat_id=%s", chat_id)
                events.put({"type": "error", "detail": str(exc)})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        yield _sse(
            {
                "type": "progress",
                "message": f"Loading messages from the last {req.days} days…",
                "percent": 2,
            }
        )
        while True:
            item = events.get()
            if item is None:
                break
            yield _sse(item)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
