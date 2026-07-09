"""Local→online handoff helpers (used by aggregator control path)."""

from __future__ import annotations

# Phrase list mirrors keywords.yaml go-online; keep for pack-level import.
HANDOFF_PHRASES = (
    "網上助理",
    "用 ChatGPT",
    "切到語音 ChatGPT",
    "online mode",
    "online assistant",
)


def match_handoff(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(p.lower() in t for p in HANDOFF_PHRASES)


def remainder_after_handoff(text: str) -> str:
    t = (text or "").strip()
    lower = t.lower()
    for p in HANDOFF_PHRASES:
        pl = p.lower()
        if lower.startswith(pl):
            return t[len(p) :].strip(" ，,：:")
        idx = lower.find(pl)
        if idx >= 0:
            rem = t[idx + len(p) :].strip(" ，,：:")
            if rem:
                return rem
    return t
