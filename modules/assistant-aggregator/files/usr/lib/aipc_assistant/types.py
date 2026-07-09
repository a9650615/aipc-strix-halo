from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_ACTIONS = frozenset(
    {
        "none",
        "session_close",
        "mode_local",
        "mode_online",
        "voice_stop",
        "inject_session",
        "inject_delta",
        "feature_enable",
        "feature_run",
    }
)


@dataclass
class TurnRequest:
    modality: str  # text | voice
    text: str = ""
    session_id: str | None = None
    prefer: str = "auto"  # auto | local | online


@dataclass
class Action:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"  # keywords | controller | system
    confidence: float = 1.0


@dataclass
class TurnResponse:
    text: str = ""
    mode_used: str = "local"
    actions: list[Action] = field(default_factory=list)
    error: str | None = None
    backend: str | None = None
