"""Out-of-band local provider health cache (no serial sweep on plan path)."""

from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "ts": 0.0,
    "litellm": {"ok": None, "detail": "unprobed"},
    "agent": {"ok": None, "detail": "self"},
}
_TTL = float(os.environ.get("AIPC_ROUTER_HEALTH_TTL_S", "30"))
_LITELLM = os.environ.get("AIPC_LITELLM_URL", "http://127.0.0.1:4000").rstrip("/")


def _probe_litellm() -> dict[str, Any]:
    url = f"{_LITELLM}/health/liveliness"
    # LiteLLM often exposes /health or /v1/models
    for u in (url, f"{_LITELLM}/v1/models", f"{_LITELLM}/health"):
        try:
            req = urllib.request.Request(u, method="GET")
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                if 200 <= resp.status < 300:
                    return {"ok": True, "detail": u, "status": resp.status}
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            continue
    return {"ok": False, "detail": "litellm unreachable"}


def refresh(*, force: bool = False) -> dict[str, Any]:
    """Refresh cache if stale. Safe to call from a background thread."""
    now = time.time()
    with _LOCK:
        age = now - float(_CACHE.get("ts") or 0)
        if not force and age < _TTL and _CACHE.get("ts"):
            return dict(_CACHE)
    litellm = _probe_litellm()
    with _LOCK:
        _CACHE["ts"] = time.time()
        _CACHE["litellm"] = litellm
        _CACHE["agent"] = {"ok": True, "detail": "orchestrator"}
        _CACHE["ttl_s"] = _TTL
        return dict(_CACHE)


def snapshot() -> dict[str, Any]:
    """Return last cache without blocking on network (may be stale/empty)."""
    with _LOCK:
        out = dict(_CACHE)
    if not out.get("ts"):
        # first call: one cheap refresh
        return refresh()
    return out


def ensure_background_refresh() -> None:
    """Start a daemon refresher once (idempotent)."""
    if getattr(ensure_background_refresh, "_started", False):
        return

    def _loop() -> None:
        while True:
            try:
                refresh()
            except Exception:
                pass
            time.sleep(max(5.0, _TTL * 0.8))

    t = threading.Thread(target=_loop, name="aipc-router-health", daemon=True)
    t.start()
    ensure_background_refresh._started = True  # type: ignore[attr-defined]
