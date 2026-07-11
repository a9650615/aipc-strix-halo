"""Build TaskEnvelope from a raw user turn."""

from __future__ import annotations

import uuid
from typing import Any

from aipc_agent.router.policy import load_policy
from aipc_agent.router.schemas import validate_envelope
from aipc_agent.router.tts_owner import speak_owner_for


def build_envelope(
    text: str,
    *,
    session_id: str = "",
    source: str = "api",
    request_id: str | None = None,
    interaction: str = "foreground",
    deadline_ms: int | None = None,
    quality: str = "balanced",
) -> dict[str, Any]:
    pol = load_policy()
    src = (source or "api").strip() or "api"
    sid = (session_id or "").strip() or "default"
    # Voice entries get a tighter interactive deadline by default
    if deadline_ms is None:
        if speak_owner_for(src, sid) == "voice_client":
            deadline_ms = 2500
        else:
            deadline_ms = 8000
    paid = "deny"
    if pol.get("paid_enabled"):
        paid = (
            str(pol.get("interactive_paid") or "ask")
            if interaction == "foreground"
            else str(pol.get("unattended_paid") or "deny")
        )
    env = {
        "request_id": request_id or str(uuid.uuid4()),
        "session_id": sid,
        "source": src,
        "text": text or "",
        "deadline_ms": int(deadline_ms),
        "interaction": interaction if interaction in ("foreground", "background") else "foreground",
        "required": ["chat"],
        "freshness": "none",
        "risk": "read",
        "data_scopes": list(pol.get("default_data_scopes") or ["prompt"]),
        "paid_policy": paid if paid in ("deny", "ask", "allow_subscription", "allow_metered") else "deny",
        "quality": quality if quality in ("fast", "balanced", "best") else "balanced",
        "tts_owner": speak_owner_for(src, sid),
        "explicit_provider": "",
    }
    return validate_envelope(env)
