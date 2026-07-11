"""Authoritative RouteDecision + legacy plan mapping."""

from __future__ import annotations

from typing import Any

from aipc_agent.router.policy import load_policy
from aipc_agent.router.shadow import plan_shadow


def is_authoritative() -> bool:
    pol = load_policy()
    if os_env_false("AIPC_ROUTER_AUTHORITATIVE"):
        return False
    if os_env_true("AIPC_ROUTER_AUTHORITATIVE"):
        return True
    return bool(pol.get("authoritative"))


def os_env_true(name: str) -> bool:
    import os

    return os.environ.get(name, "").lower() in ("1", "true", "yes", "on")


def os_env_false(name: str) -> bool:
    import os

    return os.environ.get(name, "").lower() in ("0", "false", "no", "off")


def decision_to_legacy_plan(dec: dict[str, Any], *, raw_text: str = "") -> dict[str, Any]:
    """Map RouteDecision → plan_dispatch-shaped dict (target/mode/reason)."""
    target = str(dec.get("shadow_target") or "respond")
    # Explicit local overrides that map to workers
    explicit = str(dec.get("explicit_provider") or "")
    agent = ""
    mode = "short"
    if "L3" == str(dec.get("class") or ""):
        mode = "long" if "coding" in (dec.get("required") or []) else "short"
    if target == "hermes":
        agent = "hermes"
    if explicit == "hermes":
        target = "hermes"
        agent = "hermes"
    # Subscription providers: when paid_allowed, route to subscription worker
    # (plan_dispatch still enforces session grant / ask-once before run).
    if explicit in ("codex-subscription", "claude-subscription", "grok-subscription"):
        if dec.get("paid_allowed"):
            target = "subscription"
            agent = explicit
        else:
            # Stay local-capable; record override for ask path
            if target == "respond" and "coding" in (dec.get("required") or []):
                target = "hermes"
                agent = "hermes"
            elif "coding" in (dec.get("required") or []) or "tools" in (
                dec.get("required") or []
            ):
                target = "hermes"
                agent = "hermes"
    if target == "subscription" and not agent and explicit:
        agent = explicit
    reason = ",".join(dec.get("reason_codes") or []) or "router"
    return {
        "target": target,
        "mode": mode if mode in ("short", "long") else "short",
        "reason": f"router:{reason}",
        "source": "router",
        "agent": agent,
        "original_text": raw_text or "",
        "clarify_question": "",
        "raw_text": raw_text or "",
        "router_decision": dict(dec),
        "required": list(dec.get("required") or []),
        "freshness": dec.get("freshness") or "none",
        "tts_owner": dec.get("tts_owner") or "agent",
        "request_class": dec.get("class") or "L1",
        "paid_allowed": bool(dec.get("paid_allowed")),
    }


def plan_authoritative(
    text: str,
    *,
    session_id: str = "",
    source: str = "api",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build authoritative plan from capability analysis (local-first)."""
    dec = plan_shadow(
        text,
        session_id=session_id,
        source=source,
        live_plan=None,
        request_id=request_id,
    )
    # Mark as authoritative outcome in decision extras
    dec = dict(dec)
    dec["live_target"] = dec.get("shadow_target") or "respond"
    dec["agree"] = True
    return decision_to_legacy_plan(dec, raw_text=text)
