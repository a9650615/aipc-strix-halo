"""System-audio share pack — interface + fail-soft stub.

Full PipeWire graph (mic + other sinks minus wrapper out) is deferred;
this module documents the contract and returns clear not-implemented
errors so the aggregator can fail soft.
"""

from __future__ import annotations

from typing import Any


def status() -> dict[str, Any]:
    return {
        "enabled": False,
        "implemented": False,
        "default": "mic_only",
        "note": "PipeWire virtual source not wired yet; use mic only",
    }


def allow_session(duration_s: int = 1800) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "system_audio pack not implemented (mic_only)",
        "duration_s": duration_s,
    }


def revoke() -> dict[str, Any]:
    return {"ok": True, "active": False}
