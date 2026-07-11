"""Shared usage-fetch orchestration for CLI and HTTP server.

Turns registry + config + concrete providers into the JSON snapshot shape
consumed by ``aipc-usage usage`` and ``GET /usage``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from typing import Any, Dict, List, Optional

from codexbar_usage.config import get_provider_config, load_config
from codexbar_usage.providers import PROVIDER_MODULE_MAP, instantiate_provider
from codexbar_usage.providers.base import RateWindow, UsageSnapshot
from codexbar_usage.registry import provider_by_id, provider_ids

logger = logging.getLogger(__name__)


def _resolve_api_key(provider_id: str) -> Optional[str]:
    config = load_config()
    pc = get_provider_config(config, provider_id)
    if pc and pc.api_key:
        return pc.api_key

    entry = provider_by_id(provider_id)
    env_vars = entry.env_vars if entry and entry.env_vars else ()
    for var in env_vars:
        val = os.environ.get(var)
        if val:
            return val
    return None


def _window_to_api(window: Optional[RateWindow]) -> Optional[Dict[str, Any]]:
    """Serialize a RateWindow; normalize used_percent to 0–100 for consumers."""
    if window is None:
        return None
    data = window.to_dict()
    pct = data.get("used_percent")
    if pct is not None:
        # Providers store a 0.0–1.0 fraction (up to ~2.0 for over-quota).
        # Values already in 0–100 ( > 2 and <= 200) are left alone.
        if 0.0 <= float(pct) <= 2.0:
            data["used_percent"] = round(float(pct) * 100.0, 1)
        else:
            data["used_percent"] = round(float(pct), 1)
    return data


def _snapshot_to_api(
    provider_id: str,
    result: UsageSnapshot,
    status: str = "ok",
    error: Optional[str] = None,
) -> Dict[str, Any]:
    entry = provider_by_id(provider_id)
    display = entry.name if entry else provider_id
    out: Dict[str, Any] = {
        "provider": provider_id,
        "display_name": display,
        "status": status,
        "primary": _window_to_api(result.primary),
        "secondary": _window_to_api(result.secondary),
        "identity": result.identity.to_dict() if result.identity else {},
        "updated_at": result.updated_at.isoformat(),
    }
    if result.provider_cost is not None:
        out["provider_cost"] = result.provider_cost
    if result.tertiary is not None:
        out["tertiary"] = _window_to_api(result.tertiary)
    if error:
        out["error"] = error
    return out


def _empty_snapshot(
    provider_id: str,
    status: str,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    entry = provider_by_id(provider_id)
    display = entry.name if entry else provider_id
    out: Dict[str, Any] = {
        "provider": provider_id,
        "display_name": display,
        "status": status,
        "primary": None,
        "secondary": None,
        "identity": {},
    }
    if error:
        out["error"] = error
    return out


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        # Nested event loop — spin a fresh one in this thread.
        return asyncio.new_event_loop().run_until_complete(coro)
    return asyncio.run(coro)


def fetch_provider_usage(provider_id: str, source: str = "auto") -> Dict[str, Any]:
    """Fetch one provider and return the API snapshot dict (not wrapped)."""
    del source  # reserved for future source-mode routing
    entry = provider_by_id(provider_id)
    has_fetcher = provider_id in PROVIDER_MODULE_MAP

    if not has_fetcher:
        return _empty_snapshot(provider_id, "not-implemented")

    api_key = _resolve_api_key(provider_id)
    config = load_config()
    pc = get_provider_config(config, provider_id)
    extra_config: dict[str, Any] = {}
    if pc and pc.cookie_header:
        extra_config["cookie_header"] = pc.cookie_header

    provider = instantiate_provider(
        provider_id,
        api_key=api_key,
        config=extra_config or None,
    )
    if provider is None:
        return _empty_snapshot(provider_id, "not-configured")

    # Cookie/oauth providers may work without an API key.
    auth_type = entry.auth_type if entry else "api_key"
    if not provider.api_key and auth_type == "api_key":
        return _empty_snapshot(provider_id, "no-api-key")

    try:
        result = _run_async(provider.fetch_usage())
        return _snapshot_to_api(provider_id, result, status="ok")
    except Exception as exc:
        logger.warning("provider %s fetch failed: %s", provider_id, exc)
        status = "no-api-key" if "auth" in str(exc).lower() or "credential" in str(exc).lower() else "error"
        empty = _empty_snapshot(provider_id, status, error=str(exc))
        return empty


def fetch_all_usage(
    providers: Optional[List[str]] = None,
    source: str = "auto",
) -> List[Dict[str, Any]]:
    """Fetch many providers in parallel; wrap each as ``{provider, snapshot}``."""
    ids = providers or _default_provider_ids()
    if not ids:
        return []

    def _worker(pid: str) -> tuple[str, Dict[str, Any]]:
        try:
            return pid, fetch_provider_usage(pid, source=source)
        except Exception as exc:
            return pid, _empty_snapshot(pid, "error", error=str(exc))

    results: List[Dict[str, Any]] = []
    workers = min(max(len(ids), 1), 8)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_worker, pid): pid for pid in ids}
        for fut in concurrent.futures.as_completed(futures):
            pid, snapshot = fut.result()
            results.append({"provider": pid, "snapshot": snapshot})

    # Stable order matching request list
    order = {pid: i for i, pid in enumerate(ids)}
    results.sort(key=lambda item: order.get(item["provider"], 999))
    return results


def _default_provider_ids() -> List[str]:
    config = load_config()
    if config.providers:
        return [p.id for p in config.providers if p.enabled]
    # Prefer providers that have a real fetcher, then a short core list.
    implemented = [pid for pid in provider_ids() if pid in PROVIDER_MODULE_MAP]
    if implemented:
        return implemented
    return list(PROVIDER_MODULE_MAP.keys())


def build_usage_payloads(
    providers: Optional[List[str]] = None,
    source_mode: str = "auto",
) -> List[Dict[str, Any]]:
    """Upstream-shaped CLI payloads (used by tests and JSON exporters)."""
    ids = providers or _default_provider_ids()
    payloads: List[Dict[str, Any]] = []
    for pid in ids:
        snap = fetch_provider_usage(pid, source=source_mode)
        status = snap.get("status")
        source = "api"
        entry = provider_by_id(pid)
        if entry and entry.source_type in {"cookie", "jsonl"}:
            source = "local"
        if status == "not-implemented":
            source = "unsupported"
        elif status in {"no-api-key", "not-configured"}:
            source = "config"

        usage = None
        if snap.get("primary") is not None or status == "ok":
            usage = {
                "primary": snap.get("primary"),
                "secondary": snap.get("secondary"),
                "identity": snap.get("identity"),
                "provider_cost": snap.get("provider_cost"),
            }

        payloads.append(
            {
                "provider": pid,
                "source": source,
                "usage": usage,
                "status": status,
                "error": snap.get("error"),
                "snapshot": snap,
            }
        )
    return payloads
