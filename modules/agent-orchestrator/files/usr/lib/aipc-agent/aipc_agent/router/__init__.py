"""Assistant intelligence routing — Slice A (observe / shadow).

Public surface:
  build_envelope, analyze, plan_shadow, observe_and_trace, speak_owner_for

Live worker selection still goes through graphs.plan_dispatch until Slice A
local-unification gate flips the authoritative path.
"""

from __future__ import annotations

from aipc_agent.router.analyze import analyze
from aipc_agent.router.decide import is_authoritative, plan_authoritative
from aipc_agent.router.envelope import build_envelope
from aipc_agent.router.health import ensure_background_refresh, snapshot as health_snapshot
from aipc_agent.router.policy import load_policy, policy_version
from aipc_agent.router.quality import structural_gate
from aipc_agent.router.shadow import observe_and_trace, plan_shadow
from aipc_agent.router.spoken import package_result, spoken_summary
from aipc_agent.router.stats import summarize_traces
from aipc_agent.router.tts_owner import speak_owner_for

__all__ = [
    "analyze",
    "build_envelope",
    "ensure_background_refresh",
    "health_snapshot",
    "is_authoritative",
    "load_policy",
    "observe_and_trace",
    "package_result",
    "plan_authoritative",
    "plan_shadow",
    "policy_version",
    "speak_owner_for",
    "spoken_summary",
    "structural_gate",
    "summarize_traces",
]
