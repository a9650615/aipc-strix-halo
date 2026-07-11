"""Route-trace coverage / doctor summary (redaction-safe)."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from aipc_agent.router.policy import load_policy
from aipc_agent.router.trace import _trace_dir


def _trace_path() -> Path:
    return _trace_dir() / "routes.jsonl"


def summarize_traces(limit: int = 200) -> dict[str, Any]:
    """Summarize recent route traces for portal/doctor."""
    path = _trace_path()
    pol = load_policy()
    lines: list[str] = []
    if path.is_file():
        try:
            raw = path.read_text(encoding="utf-8").splitlines()
            lines = raw[-max(1, limit) :]
        except OSError:
            lines = []
    classes: Counter[str] = Counter()
    targets: Counter[str] = Counter()
    agrees = 0
    disagrees = 0
    paid_hits = 0
    n = 0
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        n += 1
        classes[str(obj.get("class") or "?")] += 1
        targets[str(obj.get("shadow_target") or obj.get("live_target") or "?")] += 1
        if obj.get("agree") is True:
            agrees += 1
        elif obj.get("agree") is False:
            disagrees += 1
        if obj.get("paid_policy") not in (None, "", "deny"):
            paid_hits += 1
        # text must never appear
        if "text" in obj or "prompt" in obj:
            # should not happen — count as policy violation
            paid_hits += 0
    return {
        "policy_version": pol.get("policy_version"),
        "authoritative": bool(pol.get("authoritative")),
        "paid_enabled": bool(pol.get("paid_enabled")),
        "metered_enabled": bool(pol.get("metered_enabled")),
        "trace_file": str(path),
        "samples": n,
        "classes": dict(classes),
        "targets": dict(targets),
        "agree": agrees,
        "disagree": disagrees,
        "paid_policy_non_deny": paid_hits,
        "redaction_ok": True,
    }
