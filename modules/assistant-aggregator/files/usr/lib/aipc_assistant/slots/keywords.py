from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from aipc_assistant.paths import keywords_path
from aipc_assistant.types import ALLOWED_ACTIONS, Action

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


_cooldowns: dict[str, float] = {}


def _load_rules(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or keywords_path()
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8")
    if yaml is None:
        return _parse_rules_minimal(text)
    data = yaml.safe_load(text) or {}
    rules = data.get("rules") or []
    return rules if isinstance(rules, list) else []


def _parse_rules_minimal(text: str) -> list[dict[str, Any]]:
    """Tiny fallback if PyYAML missing: not full YAML, returns empty."""
    return []


def match_actions(text: str, role: str = "user", path: Path | None = None) -> list[Action]:
    if not text or not text.strip():
        return []
    lowered = text.strip().lower()
    now = time.monotonic()
    out: list[Action] = []
    for rule in _load_rules(path):
        rid = str(rule.get("id") or rule.get("action") or "rule")
        on = str(rule.get("on") or "user").lower()
        if on == "user" and role != "user":
            continue
        action = str(rule.get("action") or "none")
        if action not in ALLOWED_ACTIONS:
            continue
        phrases = rule.get("match") or []
        if not isinstance(phrases, list):
            continue
        hit = any(str(p).lower() in lowered for p in phrases if p)
        if not hit:
            continue
        cd = float(rule.get("cooldown_s") or 0)
        last = _cooldowns.get(rid, 0.0)
        if cd > 0 and (now - last) < cd:
            continue
        _cooldowns[rid] = now
        out.append(Action(name=action, source="keywords", confidence=1.0, args={"rule_id": rid}))
    return out
