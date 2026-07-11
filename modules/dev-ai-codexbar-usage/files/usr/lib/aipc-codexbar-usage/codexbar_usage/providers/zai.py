"""Z.AI monthly subscription quota provider."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import BaseProvider, ProviderIdentitySnapshot, RateWindow, UsageSnapshot

_DEFAULT_QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"
_UNIT_MINUTES = {1: 1440, 3: 60, 5: 1, 6: 10080}


def _quota_url() -> str:
    explicit = os.environ.get("Z_AI_QUOTA_URL")
    if explicit:
        return explicit
    host = os.environ.get("Z_AI_API_HOST")
    if host:
        return f"{host.rstrip('/')}/api/monitor/usage/quota/limit"
    return _DEFAULT_QUOTA_URL


def _window(entry: dict[str, Any]) -> RateWindow:
    percentage = float(entry.get("percentage") or 0)
    reset_ms = entry.get("nextResetTime")
    return RateWindow(
        used_percent=percentage / 100 if percentage > 1 else percentage,
        window_minutes=_UNIT_MINUTES.get(entry.get("unit"), 0) * int(entry.get("number") or 0) or None,
        resets_at=datetime.fromtimestamp(reset_ms / 1000, timezone.utc) if reset_ms else None,
    )


class ZaiProvider(BaseProvider):
    def __init__(self, api_key: str | None = None, config: dict[str, Any] | None = None):
        super().__init__(provider_id="zai", api_key=api_key, base_url=_quota_url(), config=config)

    def parse_usage(self, payload: dict[str, Any]) -> UsageSnapshot:
        data = payload.get("data") or {}
        limits = {
            entry.get("type"): _window(entry)
            for entry in data.get("limits") or []
            if entry.get("type") in {"TOKENS_LIMIT", "TIME_LIMIT"}
        }
        plan = data.get("planName") or data.get("plan") or data.get("plan_type") or data.get("packageName")
        return UsageSnapshot(
            primary=limits.get("TOKENS_LIMIT") or limits.get("TIME_LIMIT"),
            secondary=limits.get("TIME_LIMIT") if "TOKENS_LIMIT" in limits else None,
            identity=ProviderIdentitySnapshot(account_organization=plan),
        )

    async def fetch_usage(self) -> UsageSnapshot:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
            )
        response.raise_for_status()
        return self.parse_usage(response.json())

