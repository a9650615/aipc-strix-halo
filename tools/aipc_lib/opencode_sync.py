from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_LITELLM_BASE = "http://127.0.0.1:4000"
DEFAULT_OPENCODE_CONFIG = Path.home() / ".config" / "opencode" / "config.json"

# OpenCode's @ai-sdk/openai-compatible provider has no dynamic model-
# discovery config option (confirmed against opencode.ai/docs/providers/
# 2026-07-03 — models must be a static dict matching GET /v1/models ids).
# This module is the "dynamic" half: it queries LiteLLM itself and
# rewrites the static dict to match, so the two don't drift out of sync
# by hand.


def fetch_model_ids(base_url: str = DEFAULT_LITELLM_BASE) -> list[str]:
    """Query LiteLLM's /v1/models. Raises URLError if unreachable."""
    with urllib.request.urlopen(f"{base_url}/v1/models", timeout=5) as resp:
        data = json.load(resp)
    return [m["id"] for m in data.get("data", [])]


def sync_config(
    config_path: Path = DEFAULT_OPENCODE_CONFIG,
    base_url: str = DEFAULT_LITELLM_BASE,
    provider_id: str = "aipc",
) -> list[str]:
    """Rewrite config_path's provider.<provider_id>.models to match LiteLLM's
    current model list. Returns the list of model ids written.

    Cloud aliases (main-cloud, coder-cloud, ...) are included like everything
    else — LiteLLM doesn't distinguish them in /v1/models, and OpenCode
    doesn't care that they're remote as long as the gateway does.
    """
    model_ids = fetch_model_ids(base_url)
    if not model_ids:
        raise ValueError(f"{base_url}/v1/models returned no models")

    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    provider = config.setdefault("provider", {}).setdefault(provider_id, {})
    provider["models"] = {mid: {"name": mid} for mid in model_ids}

    current_default = config.get("model", "")
    default_id = current_default.split("/", 1)[-1] if "/" in current_default else current_default
    if default_id not in model_ids:
        config["model"] = f"{provider_id}/{model_ids[0]}"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    return model_ids
