"""Pure ops helpers shared by dashboard snapshot and SPA contracts.

Start eligibility and display state must stay truthful: unit-backed only,
never Start when already healthy (active/ready), never for n/a cards.
"""

from __future__ import annotations


def service_display_state(unit_state: str | None, health_ok: bool | None) -> str:
    unit = (unit_state or "").strip()
    if unit == "n/a":
        if health_ok is True:
            return "ready"
        if health_ok is False:
            return "down"
        return "n/a"
    return unit or "unknown"


def service_can_start(unit_state: str | None, health_ok: bool | None = None) -> bool:
    """True only for startable, non-healthy systemd-backed services."""
    unit = (unit_state or "").strip()
    if not unit or unit == "n/a":
        return False
    display = service_display_state(unit, health_ok)
    if display in ("active", "ready"):
        return False
    if unit in ("activating", "reloading"):
        return False
    return True


def service_group(service_id: str | None) -> str:
    sid = (service_id or "").strip()
    if sid in ("lemonade", "litellm", "cliproxy"):
        return "LLM"
    if sid in ("sensevoice", "kokoro", "pipecat", "mem0"):
        return "Voice"
    if sid in ("agent-activity", "hermes-webui", "codexbar"):
        return "Agent"
    return "System"
