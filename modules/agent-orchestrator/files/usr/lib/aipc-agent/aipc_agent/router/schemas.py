"""Frozen schemas for TaskEnvelope, RouteDecision, route traces (task 0.3).

Plain dicts + validation helpers — no third-party schema lib. Tests lock field
names so shadow traces stay replayable across policy versions.
"""

from __future__ import annotations

from typing import Any

POLICY_VERSION = "air-1"

ENVELOPE_KEYS = frozenset(
    {
        "request_id",
        "session_id",
        "source",
        "text",
        "deadline_ms",
        "interaction",
        "required",
        "freshness",
        "risk",
        "data_scopes",
        "paid_policy",
        "quality",
        "tts_owner",
        "explicit_provider",
    }
)

DECISION_KEYS = frozenset(
    {
        "request_id",
        "policy_version",
        "class",
        "required",
        "freshness",
        "risk",
        "data_scopes",
        "stages",
        "selected_stage",
        "live_target",
        "shadow_target",
        "agree",
        "escalation_reason",
        "paid_allowed",
        "confidence",
        "reason_codes",
        "tts_owner",
        "explicit_provider",
    }
)

TRACE_KEYS = frozenset(
    {
        "request_id",
        "policy_version",
        "class",
        "required",
        "freshness",
        "attempts",
        "escalation_reason",
        "paid_policy",
        "data_scopes",
        "result",
        "live_target",
        "shadow_target",
        "agree",
        "tts_owner",
        "text_hash",
        "plan_ms",
        "ts",
    }
)

VALID_FRESHNESS = frozenset({"none", "recent", "live"})
VALID_RISK = frozenset({"read", "write", "external_side_effect"})
VALID_INTERACTION = frozenset({"foreground", "background"})
VALID_QUALITY = frozenset({"fast", "balanced", "best"})
VALID_PAID = frozenset({"deny", "ask", "allow_subscription", "allow_metered"})
VALID_CLASS = frozenset({"L0", "L1", "L2", "L3", "L4"})


def _require_keys(obj: dict[str, Any], keys: frozenset[str], name: str) -> None:
    missing = keys - set(obj)
    if missing:
        raise ValueError(f"{name} missing keys: {sorted(missing)}")


def validate_envelope(env: dict[str, Any]) -> dict[str, Any]:
    _require_keys(env, ENVELOPE_KEYS, "TaskEnvelope")
    if env.get("freshness") not in VALID_FRESHNESS:
        raise ValueError(f"bad freshness: {env.get('freshness')!r}")
    if env.get("risk") not in VALID_RISK:
        raise ValueError(f"bad risk: {env.get('risk')!r}")
    if env.get("interaction") not in VALID_INTERACTION:
        raise ValueError(f"bad interaction: {env.get('interaction')!r}")
    if env.get("quality") not in VALID_QUALITY:
        raise ValueError(f"bad quality: {env.get('quality')!r}")
    if env.get("paid_policy") not in VALID_PAID:
        raise ValueError(f"bad paid_policy: {env.get('paid_policy')!r}")
    if not isinstance(env.get("required"), list):
        raise ValueError("required must be a list")
    if not isinstance(env.get("data_scopes"), list):
        raise ValueError("data_scopes must be a list")
    return env


def validate_decision(dec: dict[str, Any]) -> dict[str, Any]:
    _require_keys(dec, DECISION_KEYS, "RouteDecision")
    if dec.get("class") not in VALID_CLASS:
        raise ValueError(f"bad class: {dec.get('class')!r}")
    return dec


def validate_trace(tr: dict[str, Any]) -> dict[str, Any]:
    _require_keys(tr, TRACE_KEYS, "RouteTrace")
    return tr
