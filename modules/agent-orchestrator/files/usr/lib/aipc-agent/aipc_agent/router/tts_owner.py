"""Single TTS owner per entry (anti dual-paplay)."""

from __future__ import annotations


def speak_owner_for(source: str, session_id: str = "") -> str:
    """Return who may speak for this turn: voice_client | krunner | agent | none."""
    src = (source or "").strip().lower()
    sid = (session_id or "").strip().lower()
    if src in ("voice", "wake", "ptt", "aipc-voice-once", "voice-once", "voice-stream"):
        return "voice_client"
    if any(k in sid for k in ("voice", "wake", "ptt", "aipc-voice")):
        return "voice_client"
    if src in ("krunner", "spotlight") or sid in ("krunner", "spotlight", "desktop"):
        return "krunner"
    if src in ("notify", "portal", "api", "curl", "test", ""):
        # portal/api: agent may speak only if no client TTS (policy)
        return "agent"
    return "agent"
