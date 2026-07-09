"""Online session timeout helpers (idle / max duration)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

from aipc_assistant.paths import inject_policy_path


@dataclass
class SessionWatch:
    started: float = field(default_factory=time.monotonic)
    last_event: float = field(default_factory=time.monotonic)
    idle_stop_s: float = 90.0
    max_session_s: float = 1800.0

    def touch(self) -> None:
        self.last_event = time.monotonic()

    def expired(self) -> str | None:
        now = time.monotonic()
        if now - self.started >= self.max_session_s:
            return "max_session"
        if now - self.last_event >= self.idle_stop_s:
            return "idle"
        return None


def load_timeouts(path: Path | None = None) -> tuple[float, float]:
    p = path or inject_policy_path()
    idle, mx = 90.0, 1800.0
    if p.is_file() and yaml is not None:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        t = data.get("timeouts") or {}
        if isinstance(t, dict):
            idle = float(t.get("idle_stop_s") or idle)
            mx = float(t.get("max_session_s") or mx)
    return idle, mx


def new_watch() -> SessionWatch:
    idle, mx = load_timeouts()
    return SessionWatch(idle_stop_s=idle, max_session_s=mx)


def apply_timeout_if_needed(watch: SessionWatch, online_backend: Any) -> str | None:
    reason = watch.expired()
    if not reason:
        return None
    try:
        if hasattr(online_backend, "voice_stop"):
            online_backend.voice_stop()
    except Exception:
        pass
    try:
        if hasattr(online_backend, "session_close"):
            online_backend.session_close()
    except Exception:
        pass
    return reason
