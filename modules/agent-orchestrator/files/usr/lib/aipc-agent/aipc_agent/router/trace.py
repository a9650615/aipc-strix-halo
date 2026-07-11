"""Redaction-safe route traces (Slice A)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _trace_dir() -> Path:
    env = os.environ.get("AIPC_ROUTER_TRACE_DIR")
    if env:
        return Path(env)
    # Prefer agent state dir used on this machine
    for p in (
        Path("/var/lib/aipc-agent/router-traces"),
        Path(os.environ.get("XDG_STATE_HOME", "")) / "aipc-agent" / "router-traces"
        if os.environ.get("XDG_STATE_HOME")
        else None,
        Path.home() / ".local" / "state" / "aipc-agent" / "router-traces",
        Path("/tmp/aipc-router-traces"),
    ):
        if p is None:
            continue
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except OSError:
            continue
    return Path("/tmp/aipc-router-traces")


def write_trace(trace: dict[str, Any]) -> Path | None:
    """Append one JSON line; never stores full user text (hash only)."""
    # Defense: strip accidental full text
    safe = {k: v for k, v in trace.items() if k not in ("text", "prompt", "payload")}
    line = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    d = _trace_dir()
    path = d / "routes.jsonl"
    with _LOCK:
        try:
            d.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            return path
        except OSError as exc:
            print(f"aipc-agent: router trace write fail: {exc}", flush=True)
            return None
