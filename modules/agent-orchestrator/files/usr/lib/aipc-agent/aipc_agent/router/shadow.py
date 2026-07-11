"""Shadow planner: propose stages without changing live dispatch."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from aipc_agent.router.analyze import analyze
from aipc_agent.router.envelope import build_envelope
from aipc_agent.router.policy import load_policy, policy_version
from aipc_agent.router.schemas import validate_decision, validate_trace
from aipc_agent.router.trace import write_trace

# Map required caps → preferred local stage id (Slice A: local only)
_CAP_STAGE = {
    "deterministic_local": "local-deterministic",
    "chat": "local-chat",
    "job_status": "local-job-status",
    "screen": "local-screen",
    "usage_tools": "local-daily",
    "daily_tools": "local-daily",
    "files": "local-daily",
    "web_search": "local-hermes",
    "grounding": "local-hermes",
    "coding": "local-hermes",
    "tools": "local-hermes",
}

# Map stage → legacy live target for agreement check
_STAGE_TARGET = {
    "local-deterministic": "respond",
    "local-chat": "respond",
    "local-job-status": "job_status",
    "local-screen": "screen_see",
    "local-daily": "daily_assistant",
    "local-hermes": "hermes",
    "local-coder": "coder",
    "subscription-cli": "subscription",
    "subscription-ask": "subscription",
}


def _stages_for(required: list[str], *, paid_enabled: bool) -> list[str]:
    stages: list[str] = []
    for cap in required:
        st = _CAP_STAGE.get(cap)
        if st and st not in stages:
            stages.append(st)
    if not stages:
        stages = ["local-chat"]
    # Slice A: never append subscription/metered stages
    if paid_enabled:
        stages.append("subscription-ask")
    return stages


def _shadow_target(stages: list[str]) -> str:
    if not stages:
        return "respond"
    return _STAGE_TARGET.get(stages[0], "respond")


def plan_shadow(
    text: str,
    *,
    session_id: str = "",
    source: str = "api",
    live_plan: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Return a RouteDecision for shadow compare. Does not execute workers."""
    t0 = time.monotonic()
    pol = load_policy()
    env = build_envelope(
        text,
        session_id=session_id,
        source=source,
        request_id=request_id,
    )
    analysis = analyze(env)
    stages = _stages_for(
        list(analysis.get("required") or ["chat"]),
        paid_enabled=bool(pol.get("paid_enabled")),
    )
    shadow_tgt = _shadow_target(stages)
    live_tgt = ""
    if live_plan:
        live_tgt = str(live_plan.get("target") or "")
    # Agreement: same worker family
    agree = bool(live_tgt) and (
        live_tgt == shadow_tgt
        or (live_tgt == "hermes" and shadow_tgt in ("hermes", "coder"))
        or (live_tgt == "coder" and shadow_tgt == "hermes")
        or (live_tgt == "daily_assistant" and shadow_tgt in ("daily_assistant", "hermes"))
    )
    # Subscription canary: paid_allowed follows policy.paid_enabled (not metered).
    # Automatic use still requires grant; auto_subscription is a separate flip.
    explicit = str(analysis.get("explicit_provider") or "")
    escalation = ""
    paid_enabled = bool(pol.get("paid_enabled"))
    # Subscription canary may be enabled by paid_enabled flip (metered stays separate).
    paid_allowed = paid_enabled
    # When paid is on, subscription stages may be candidates for explicit providers
    if paid_allowed and explicit in (
        "codex-subscription",
        "claude-subscription",
        "grok-subscription",
    ):
        if "subscription-cli" not in stages:
            stages.append("subscription-cli")
        # Named provider → subscription target (grant enforced in plan_dispatch/node)
        shadow_tgt = "subscription"
        if not pol.get("auto_subscription"):
            escalation = "explicit_provider_needs_grant"
        else:
            stages = ["subscription-cli", *[s for s in stages if s != "subscription-cli"]]
    elif explicit and explicit not in ("hermes",) and not paid_allowed:
        escalation = "explicit_provider_deferred_paid_off"

    plan_ms = (time.monotonic() - t0) * 1000.0
    dec: dict[str, Any] = {
        "request_id": analysis["request_id"],
        "policy_version": policy_version(),
        "class": analysis.get("request_class") or "L1",
        "required": list(analysis.get("required") or []),
        "freshness": analysis.get("freshness") or "none",
        "risk": analysis.get("risk") or "read",
        "data_scopes": list(analysis.get("data_scopes") or ["prompt"]),
        "stages": stages,
        "selected_stage": stages[0] if stages else "local-chat",
        "live_target": live_tgt,
        "shadow_target": shadow_tgt,
        "agree": agree if live_tgt else None,
        "escalation_reason": escalation,
        "paid_allowed": paid_allowed,
        "confidence": float(analysis.get("confidence") or 0.5),
        "reason_codes": list(analysis.get("reason_codes") or []),
        "tts_owner": analysis.get("tts_owner") or "agent",
        "explicit_provider": explicit,
        # non-schema extras for logs/trace
        "plan_ms": round(plan_ms, 2),
        "session_id": analysis.get("session_id") or session_id,
        "source": analysis.get("source") or source,
        "paid_policy": analysis.get("paid_policy") or "deny",
    }
    validate_decision(dec)
    return dec


def observe_and_trace(
    text: str,
    *,
    session_id: str = "",
    source: str = "api",
    live_plan: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """Shadow plan + optional redaction-safe trace. Never raises; never changes live."""
    pol = load_policy()
    if not pol.get("shadow", True):
        return None
    try:
        dec = plan_shadow(
            text,
            session_id=session_id,
            source=source,
            live_plan=live_plan,
            request_id=request_id,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: router shadow fail: {exc}", flush=True)
        return None

    if pol.get("trace", True):
        try:
            th = hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()[:16]
            tr = {
                "request_id": dec["request_id"],
                "policy_version": dec["policy_version"],
                "class": dec["class"],
                "required": dec["required"],
                "freshness": dec["freshness"],
                "attempts": [
                    {
                        "provider": "shadow",
                        "outcome": "proposed",
                        "stage": dec.get("selected_stage"),
                        "latency_ms": dec.get("plan_ms") or 0,
                    }
                ],
                "escalation_reason": dec.get("escalation_reason") or "",
                "paid_policy": "deny",
                "data_scopes": dec.get("data_scopes") or ["prompt"],
                "result": "shadow",
                "live_target": dec.get("live_target") or "",
                "shadow_target": dec.get("shadow_target") or "",
                "agree": dec.get("agree"),
                "tts_owner": dec.get("tts_owner") or "",
                "text_hash": th,
                "plan_ms": dec.get("plan_ms") or 0,
                "ts": time.time(),
            }
            write_trace(validate_trace(tr))
        except Exception as exc:  # noqa: BLE001
            print(f"aipc-agent: router trace fail: {exc}", flush=True)

    # Compact log line for journal
    try:
        print(
            "aipc-agent: router-shadow "
            f"class={dec.get('class')} live={dec.get('live_target') or '-'} "
            f"shadow={dec.get('shadow_target')} agree={dec.get('agree')} "
            f"req={','.join(dec.get('required') or [])} "
            f"tts={dec.get('tts_owner')} ms={dec.get('plan_ms')}",
            flush=True,
        )
    except Exception:
        pass
    return dec
