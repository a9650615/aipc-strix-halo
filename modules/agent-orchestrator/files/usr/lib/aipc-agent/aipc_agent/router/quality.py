"""Structural quality gates (reuse grounding; no parallel truth stack)."""

from __future__ import annotations

import re
from typing import Any

_EMPTY_TEMPLATES = (
    "error:",
    "timeout",
    "timed out",
    "no response",
    "empty reply",
    "助手暂时无法",
    "暂时无法完成",
)


def structural_gate(
    *,
    reply: str,
    required: list[str] | None = None,
    freshness: str = "none",
    trail: str = "",
) -> dict[str, Any]:
    """Return {ok, reasons, incomplete}.

    Cheap structural checks only — not a second model judge.
    """
    text = (reply or "").strip()
    reasons: list[str] = []
    req = list(required or [])

    if len(text) < 2:
        return {"ok": False, "reasons": ["empty"], "incomplete": True}

    low = text.lower()
    if any(t in low for t in _EMPTY_TEMPLATES) and len(text) < 80:
        reasons.append("error_template")

    if text.endswith("…") or text.endswith("..."):
        if len(text) < 40:
            reasons.append("truncated")

    needs_ground = (
        freshness in ("live", "recent")
        or "grounding" in req
        or "web_search" in req
    )
    if needs_ground:
        try:
            from aipc_agent.grounding import has_tool_grounding

            if not has_tool_grounding(reply=text, trail=trail):
                # Soft fail for voice-short replies that still cite a source line
                if not re.search(r"(https?://|来源|來源|依据|依據|根据|根據)", text):
                    reasons.append("ungrounded_live")
        except Exception:
            pass

    # Any topic: if tool trail had media but reply dropped all URLs, flag it
    try:
        from aipc_agent.media_present import missing_media_reasons

        for r in missing_media_reasons(text, trail or ""):
            if r not in reasons:
                reasons.append(r)
    except Exception:
        pass

    ok = "empty" not in reasons and "error_template" not in reasons
    incomplete = (
        (not ok)
        or ("ungrounded_live" in reasons)
        or ("truncated" in reasons)
        or ("media_dropped" in reasons)
    )
    # thin_media_set is advisory
    return {
        "ok": ok
        and "ungrounded_live" not in reasons
        and "media_dropped" not in reasons,
        "reasons": reasons,
        "incomplete": incomplete or ("thin_media_set" in reasons),
    }


def maybe_mark_incomplete(reply: str, gate: dict[str, Any]) -> str:
    """Append a short incomplete cue when structural gate fails (not for empty)."""
    if gate.get("ok"):
        return reply
    if not (reply or "").strip():
        return reply
    reasons = gate.get("reasons") or []
    # Promote media URLs from tool trail into the user-visible reply (any topic)
    if "media_dropped" in reasons or "thin_media_set" in reasons:
        try:
            from aipc_agent.media_present import promote_media_from_trail

            # trail may be passed via gate callers separately — store on gate if present
            trail = str(gate.get("trail") or "")
            if trail:
                reply = promote_media_from_trail(reply, trail)
        except Exception:
            pass
    if "ungrounded_live" in reasons:
        cue = "\n\n（此回答缺少可核对来源，建议再说「用工具查一下」复核。）"
        if cue.strip() not in reply:
            return (reply.rstrip() + cue)[:2000]
    return reply
