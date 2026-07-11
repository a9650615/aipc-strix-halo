"""Quota-gated GLM tool; all inference goes through the local LiteLLM gateway."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

LITELLM_CHAT_URL = "http://127.0.0.1:4000/v1/chat/completions"
_SECRET = re.compile(
    r"(?:api[_ -]?key|password|secret|token)\s*[:=]\s*\S{8,}"
    r"|authorization\s*:\s*bearer\s+\S+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----",
    re.IGNORECASE,
)


def _quota_available(result: dict[str, Any]) -> bool:
    if result.get("status") != "ok":
        return False
    for provider in result.get("providers") or []:
        if (provider.get("id") or provider.get("provider")) != "zai":
            continue
        if provider.get("status") in {"error", "not_configured", "not-implemented"}:
            return False
        try:
            updated = datetime.fromisoformat(str(provider["updated_at"]).replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - updated).total_seconds()
            max_age = float(os.environ.get("AIPC_GLM_QUOTA_MAX_AGE", "300"))
            return -60 <= age <= max_age and float(provider.get("remaining_percent") or 0) > 0
        except (KeyError, TypeError, ValueError):
            return False
    return False


def next_data_scopes(current: list[str], tool_names: list[str]) -> list[str]:
    if current != ["prompt"] or any(name != "ask_glm" for name in tool_names):
        return ["private"]
    return ["prompt"]


def _lookup_zai(_: str) -> dict[str, Any]:
    from aipc_agent_tools_usage import lookup_usage

    return lookup_usage("zai")


def _post_glm(prompt: str) -> str:
    request = urllib.request.Request(
        LITELLM_CHAT_URL,
        data=json.dumps(
            {"model": "glm-cloud", "messages": [{"role": "user", "content": prompt}]}
        ).encode(),
        headers={"Authorization": "Bearer aipc-local", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(
        request, timeout=float(os.environ.get("AIPC_GLM_TIMEOUT", "180"))
    ) as response:
        payload = json.load(response)
    return str(payload["choices"][0]["message"]["content"]).strip()


def ask_glm(
    prompt: str,
    data_scope: str,
    interaction: str,
    *,
    lookup: Callable[[str], dict[str, Any]] | None = None,
    post: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    if not prompt.strip():
        return {"status": "error", "tool": "ask_glm", "detail": "prompt is empty"}
    if data_scope != "prompt" or interaction != "foreground":
        return {
            "status": "local_only",
            "tool": "ask_glm",
            "detail": "GLM allows foreground prompt-only requests",
        }
    if _SECRET.search(prompt):
        return {
            "status": "local_only",
            "tool": "ask_glm",
            "detail": "prompt contains credential-shaped data",
        }
    try:
        quota = (lookup or _lookup_zai)("zai")
    except (ImportError, OSError, ValueError) as exc:
        return {"status": "local_only", "tool": "ask_glm", "detail": str(exc)}
    if not _quota_available(quota):
        return {
            "status": "local_only",
            "tool": "ask_glm",
            "detail": "Z.AI quota unavailable or exhausted",
        }
    try:
        content = (post or _post_glm)(prompt)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "tool": "ask_glm", "detail": str(exc)}
    return {"status": "ok", "tool": "ask_glm", "content": content}
