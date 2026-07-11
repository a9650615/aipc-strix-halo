from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from aipc_lib.models import DEFAULT_MANIFEST, load_manifest

DEFAULT_LITELLM_BASE = "http://127.0.0.1:4000"
DEFAULT_OPENCODE_CONFIG = Path.home() / ".config" / "opencode" / "config.json"
LEMONADE_PORT_FILE = Path("/etc/aipc/env.d/llm-lemonade/port")

# OpenCode's @ai-sdk/openai-compatible provider has no dynamic model-
# discovery config option (confirmed against opencode.ai/docs/providers/
# 2026-07-03 — models must be a static dict matching GET /v1/models ids).
# This module is the "dynamic" half: it queries LiteLLM itself and
# rewrites the static dict to match, so the two don't drift out of sync
# by hand.

# Aliases that exist in the LiteLLM model_list but aren't meant for
# interactive chat — embed-bge is an embeddings-only endpoint, intent-3b
# is a classification model. Listing them in OpenCode's model picker next
# to actual chat models is confusing (a user reported the mixed list
# "isn't intuitive") and selecting either would just error.
NON_CHAT_ALIASES = {"embed-bge", "intent-3b"}

# NPU compact / title / light-work lane (LiteLLM → Lemonade FLM). Kept off the
# Vulkan coder-agentic llama-server slots so compact prefill does not stall
# the tool loop. See modules/llm-litellm config alias coder-compact.
COMPACT_ALIAS = "coder-compact"
# Recipe + LiteLLM model_info for coding/compact local GGUF/FLM lanes.
# Lemonade /api/v1/models often advertises the card max (e.g. 262144) which
# is larger than the loaded --ctx-size (131072); OpenCode must compact
# against the real ceiling or it hits backend context_length_exceeded.
CODING_CONTEXT_CAP = 131072


def fetch_model_ids(base_url: str = DEFAULT_LITELLM_BASE) -> list[str]:
    """Query LiteLLM's /v1/models. Raises URLError if unreachable."""
    with urllib.request.urlopen(f"{base_url}/v1/models", timeout=5) as resp:
        data = json.load(resp)
    return [m["id"] for m in data.get("data", [])]


def _display_names(model_ids: list[str], manifest_path: Path) -> dict[str, str]:
    """alias -> "alias (model_id, size)" using models.yaml for the concrete
    model_id and size_gb (the closest available proxy for parameter count —
    models.yaml has no separate params field, and model_id tags spell it
    inconsistently across backends: "7b-instruct", "e4b", "35b-a3b", ...).
    size_gb is "cloud" (string) for remote aliases — shown as-is, not "GB".
    Falls back to the bare alias for anything not in the manifest."""
    by_alias = {e.alias: e for e in load_manifest(manifest_path)}
    names: dict[str, str] = {}
    for mid in model_ids:
        entry = by_alias.get(mid)
        if entry is None:
            names[mid] = mid
            continue
        size = "cloud" if entry.size_gb == "cloud" else f"{entry.size_gb}GB"
        names[mid] = f"{mid} ({entry.model_id}, {size})"
    return names


def _lemonade_base_url() -> str:
    port = LEMONADE_PORT_FILE.read_text().strip() if LEMONADE_PORT_FILE.exists() else "8001"
    return f"http://127.0.0.1:{port}"


def _lemonade_context_limits(base_url: str) -> dict[str, int]:
    """Lemonade model_id -> max_context_window, from Lemonade's own
    /api/v1/models (not LiteLLM's /v1/models, which doesn't carry this).
    Returns {} if Lemonade is unreachable -- a miss just means "unknown,
    omit limit" to callers, not a hard failure, since aliases on other
    backends (cloud, ollama) don't need Lemonade up at all."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/v1/models", timeout=5) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    return {
        m["id"]: m["max_context_window"]
        for m in data.get("data", [])
        if "max_context_window" in m
    }


def _limits(model_ids: list[str], manifest_path: Path) -> dict[str, dict[str, int]]:
    """alias -> {"context": N, "output": N} for aliases backed by Lemonade,
    so OpenCode's own auto-compact (compaction.auto, on by default) has a
    ceiling to compact against instead of only finding out when the
    backend 400s with context_length_exceeded (hardware-verified
    2026-07-05: a 264,989-token ornith-35b request did exactly that).
    Aliases on other backends are left out, same as today -- no known
    limit beats a guessed one that's wrong in either direction."""
    by_alias = {e.alias: e for e in load_manifest(manifest_path)}
    lemonade_ids = {
        mid: by_alias[mid].model_id
        for mid in model_ids
        if by_alias.get(mid) and by_alias[mid].backend == "lemonade"
    }
    if not lemonade_ids:
        return {}
    ctx_by_model_id = _lemonade_context_limits(_lemonade_base_url())
    limits: dict[str, dict[str, int]] = {}
    for alias, model_id in lemonade_ids.items():
        ctx = ctx_by_model_id.get(model_id)
        if ctx is None:
            continue
        # Prefer the loaded recipe ceiling over the GGUF card max.
        ctx = min(int(ctx), CODING_CONTEXT_CAP)
        # Reserve a completion budget out of the same window so a long
        # generation can't blow the ceiling from the other direction.
        limits[alias] = {"context": ctx, "output": min(ctx // 4, 16384)}
    return limits


def sync_config(
    config_path: Path = DEFAULT_OPENCODE_CONFIG,
    base_url: str = DEFAULT_LITELLM_BASE,
    provider_id: str = "aipc",
    manifest_path: Path = DEFAULT_MANIFEST,
    exclude: set[str] = NON_CHAT_ALIASES,
) -> list[str]:
    """Rewrite config_path's provider.<provider_id>.models to match LiteLLM's
    current model list (minus *exclude*). Returns the list of model ids
    written, with friendly "alias (model_id)" display names sourced from
    models.yaml where available.

    Cloud aliases (main-cloud, coder-cloud, ...) are included like everything
    else — LiteLLM doesn't distinguish them in /v1/models, and OpenCode
    doesn't care that they're remote as long as the gateway does.

    When ``coder-compact`` is available, sets ``small_model`` to that alias
    and enables ``compaction.prune`` so light/compact work stays on NPU.
    """
    all_ids = fetch_model_ids(base_url)
    model_ids = [mid for mid in all_ids if mid not in exclude]
    if not model_ids:
        raise ValueError(f"{base_url}/v1/models returned no chat-eligible models")

    names = _display_names(model_ids, manifest_path)
    limits = _limits(model_ids, manifest_path)

    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    provider = config.setdefault("provider", {}).setdefault(provider_id, {})
    provider["models"] = {
        mid: {"name": names[mid], **({"limit": limits[mid]} if mid in limits else {})}
        for mid in model_ids
    }

    current_default = config.get("model", "")
    default_id = current_default.split("/", 1)[-1] if "/" in current_default else current_default
    if default_id not in model_ids:
        config["model"] = f"{provider_id}/{model_ids[0]}"

    if COMPACT_ALIAS in model_ids:
        config["small_model"] = f"{provider_id}/{COMPACT_ALIAS}"
        compaction = config.setdefault("compaction", {})
        compaction.setdefault("auto", True)
        compaction["prune"] = True
        compaction.setdefault("reserved", 12000)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    return model_ids
