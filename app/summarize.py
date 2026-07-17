"""Local extractive summarization focused on overall discussion context."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Optional

STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "if",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "he",
    "she",
    "they",
    "them",
    "their",
    "with",
    "from",
    "by",
    "about",
    "into",
    "over",
    "after",
    "before",
    "so",
    "than",
    "too",
    "very",
    "just",
    "not",
    "no",
    "yes",
    "ok",
    "okay",
    "oh",
    "um",
    "uh",
    "like",
    "get",
    "got",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "can",
    "could",
    "should",
    "im",
    "ive",
    "dont",
    "didnt",
    "cant",
    "wont",
    "thats",
    "whats",
    "theres",
    "heres",
    "lol",
    "haha",
    "hahaha",
    "http",
    "https",
    "www",
    "com",
    "msg",
}

# Noise that shows up in iMessage attributed bodies / system junk
NOISE_TOKEN_RE = re.compile(
    r"(kimmessage|attributename|nsstring|plain-text|utm_|https?|www\.)",
    re.I,
)


def _clean_text(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokenize(text: str) -> list[str]:
    tokens = []
    for t in re.findall(r"[a-z0-9']+", _clean_text(text).lower()):
        if t in STOPWORDS or len(t) < 3:
            continue
        if NOISE_TOKEN_RE.search(t):
            continue
        if t.isdigit():
            continue
        tokens.append(t)
    return tokens


def _sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", _clean_text(text))
    return [p.strip() for p in parts if p and len(p.strip()) > 12]


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _speaker(m: dict[str, Any]) -> str:
    if m.get("is_from_me"):
        return "You"
    return m.get("sender_name") or m.get("sender") or "Them"


def _message_score(tokens: list[str], df: Counter, n_docs: int) -> float:
    if not tokens:
        return 0.0
    tf = Counter(tokens)
    base = sum(
        (1 + math.log(count)) * math.log(1 + n_docs / (1 + df[tok]))
        for tok, count in tf.items()
    )
    # Prefer substantive messages over short reactions.
    length_bonus = min(len(tokens), 40) / 40.0
    return (base / math.sqrt(len(tokens))) * (0.55 + 0.45 * length_bonus)


def _theme_clusters(messages: list[dict[str, Any]], doc_tokens: list[list[str]]) -> list[str]:
    """Find recurring discussion themes that appear across multiple messages."""
    df = Counter()
    for tokens in doc_tokens:
        df.update(set(tokens))

    # Theme candidates must appear in several messages, not just once.
    min_docs = 2 if len(messages) < 20 else 3
    candidates = [term for term, count in df.items() if count >= min_docs]
    candidates.sort(key=lambda t: (df[t], len(t)), reverse=True)

    themes: list[str] = []
    for term in candidates:
        if any(term in existing or existing in term for existing in themes):
            continue
        themes.append(term)
        if len(themes) >= 6:
            break
    return themes


def _representative_excerpts(
    messages: list[dict[str, Any]],
    doc_tokens: list[list[str]],
    themes: list[str],
    *,
    limit: int = 5,
) -> list[str]:
    """Pick excerpts that best represent the overall themes of the discussion."""
    df = Counter()
    for tokens in doc_tokens:
        df.update(set(tokens))
    n_docs = max(len(messages), 1)
    theme_set = set(themes)

    scored: list[tuple[float, str, set[str]]] = []
    for m, tokens in zip(messages, doc_tokens):
        if len(tokens) < 4:
            continue
        score = _message_score(tokens, df, n_docs)
        overlap = len(set(tokens) & theme_set)
        score *= 1.0 + 0.35 * overlap
        text = _clean_text(m["text"])
        if len(text) > 220:
            text = text[:217] + "…"
        scored.append((score, f"{_speaker(m)}: {text}", set(tokens)))

    scored.sort(key=lambda x: x[0], reverse=True)
    picks: list[str] = []
    seen: list[set[str]] = []
    for _, line, tokens in scored:
        if any(len(tokens & prev) / max(len(tokens | prev), 1) > 0.65 for prev in seen):
            continue
        picks.append(line)
        seen.append(tokens)
        if len(picks) >= limit:
            break
    return picks


def _discussion_arc(
    messages: list[dict[str, Any]],
    doc_tokens: list[list[str]],
    themes: list[str],
) -> str:
    """Build a short narrative of what the overall discussion was about."""
    name = "this conversation"
    # Caller can prepend display name; keep this focused on substance.

    if not messages:
        return "No discussion content available."

    n = len(messages)
    # Split into early / late thirds to describe how the discussion moved.
    early_cut = max(1, n // 3)
    late_cut = max(early_cut + 1, (2 * n) // 3)
    early_tokens = [t for tokens in doc_tokens[:early_cut] for t in tokens]
    late_tokens = [t for tokens in doc_tokens[late_cut:] for t in tokens]
    early_top = [t for t, _ in Counter(early_tokens).most_common(4) if t in themes or True]
    late_top = [t for t, _ in Counter(late_tokens).most_common(4)]

    # Prefer theme-overlapping terms for readability
    early_focus = [t for t in early_top if t in themes][:3] or early_top[:3]
    late_focus = [t for t in late_top if t in themes][:3] or late_top[:3]

    parts: list[str] = []
    if themes:
        parts.append(
            "Overall, the discussion centers on "
            + ", ".join(themes[:4])
            + ("." if len(themes) <= 4 else ", and related points.")
        )
    else:
        parts.append("The exchange covers day-to-day updates without one dominant topic.")

    if early_focus:
        parts.append("It starts around " + ", ".join(early_focus) + ".")
    if late_focus and late_focus != early_focus:
        parts.append("More recently, the conversation turns toward " + ", ".join(late_focus) + ".")

    # Who drove substance
    by_speaker: dict[str, int] = defaultdict(int)
    for m, tokens in zip(messages, doc_tokens):
        if len(tokens) >= 5:
            by_speaker[_speaker(m)] += 1
    if by_speaker:
        lead = max(by_speaker.items(), key=lambda kv: kv[1])[0]
        parts.append(f"Most of the substantive back-and-forth comes from {lead}.")

    return " ".join(parts)


def summarize_thread(
    thread: dict[str, Any],
    *,
    max_sentences: int = 5,
    max_messages: int = 120,
) -> dict[str, Any]:
    cleaned = []
    for m in thread.get("messages", []):
        text = _clean_text(m.get("text") or "")
        if not text:
            continue
        # Drop pure-link / junk messages
        if len(_tokenize(text)) < 1 and "http" in (m.get("text") or "").lower():
            continue
        cleaned.append({**m, "text": text})
    messages = cleaned[-max_messages:]

    if not messages:
        return {
            "summary": "No text messages available to summarize in this thread.",
            "highlights": [],
            "topics": [],
            "stats": {
                "message_count": 0,
                "from_me": 0,
                "from_them": 0,
                "first_at": None,
                "last_at": None,
            },
            "method": "extractive",
        }

    from_me = sum(1 for m in messages if m.get("is_from_me"))
    from_them = len(messages) - from_me
    first_at = messages[0].get("sent_at")
    last_at = messages[-1].get("sent_at")
    name = thread.get("display_name") or "This conversation"

    doc_tokens = [_tokenize(m["text"]) for m in messages]
    themes = _theme_clusters(messages, doc_tokens)
    arc = _discussion_arc(messages, doc_tokens, themes)
    highlights = _representative_excerpts(
        messages, doc_tokens, themes, limit=max_sentences
    )

    summary = (
        f"{name}: over {len(messages)} messages in this window "
        f"({from_me} from you, {from_them} from others). {arc}"
    )

    return {
        "summary": summary,
        "highlights": highlights,
        "topics": themes,
        "stats": {
            "message_count": len(messages),
            "from_me": from_me,
            "from_them": from_them,
            "first_at": first_at,
            "last_at": last_at,
        },
        "method": "extractive",
    }
