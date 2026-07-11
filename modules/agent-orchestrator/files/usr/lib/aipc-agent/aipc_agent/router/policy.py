"""Versioned routing policy (Slice B: confirmed subscription CLI delegation)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from aipc_agent.router.schemas import POLICY_VERSION

# Defaults match design.md (user-approved 2026-07-10; subscription-only)
_DEFAULTS: dict[str, Any] = {
    "policy_version": POLICY_VERSION,
    "slice": "B",
    "authoritative": True,  # local unification; kill-switch via env/config
    "paid_enabled": True,
    "auto_subscription": False,
    "interactive_paid": "ask",
    "subscription_ask_scope": "task",  # one confirmation per delegated task
    "unattended_paid": "deny",
    "metered_enabled": False,  # no API-token path; subscription CLIs only
    "metered_hard_cap": None,
    "default_data_scopes": ["prompt"],
    "shadow": True,
    "trace": True,
}


def policy_version() -> str:
    return str(load_policy().get("policy_version") or POLICY_VERSION)


def _config_paths() -> list[Path]:
    env = os.environ.get("AIPC_AGENT_ROUTING_POLICY")
    paths: list[Path] = []
    if env:
        paths.append(Path(env))
    paths.append(Path("/etc/aipc/agent/routing-policy.yaml"))
    # In-repo ship path (render target + live hotfix fallback)
    here = Path(__file__).resolve()
    # .../aipc_agent/router/policy.py → module files/etc
    for up in here.parents:
        cand = up / "etc" / "aipc" / "agent" / "routing-policy.yaml"
        if cand.is_file():
            paths.append(cand)
            break
    return paths


def load_policy() -> dict[str, Any]:
    """Load policy YAML if present; else defaults. Never raises."""
    out = dict(_DEFAULTS)
    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None  # type: ignore
    for p in _config_paths():
        try:
            if not p.is_file():
                continue
            raw = p.read_text(encoding="utf-8")
            if yaml is not None:
                data = yaml.safe_load(raw) or {}
            else:
                # Minimal fallback: ignore file content if no PyYAML
                data = {}
            if isinstance(data, dict):
                out.update({k: v for k, v in data.items() if v is not None})
                out["_loaded_from"] = str(p)
                break
        except Exception:
            continue
    # Env overrides for observe mode
    if os.environ.get("AIPC_ROUTER_SHADOW", "").lower() in ("0", "false", "no", "off"):
        out["shadow"] = False
    if os.environ.get("AIPC_ROUTER_TRACE", "").lower() in ("0", "false", "no", "off"):
        out["trace"] = False
    # Slice A hard stop: never enable paid from config alone without slice flag
    if str(out.get("slice") or "A").upper() == "A":
        out["paid_enabled"] = False
    # Deployment policy: no metered API / token path unless explicitly re-enabled
    if out.get("metered_enabled") is None:
        out["metered_enabled"] = False
    if not out.get("metered_enabled"):
        out["metered_hard_cap"] = None
    return out
