from __future__ import annotations

import os
import time
from pathlib import Path

import yaml

from aipc_lib.models import DEFAULT_MANIFEST, load_manifest
from aipc_lib.opencode_sync import DEFAULT_LITELLM_BASE, NON_CHAT_ALIASES, fetch_model_ids

DEFAULT_HERMES_CONFIG = Path.home() / ".hermes" / "config.yaml"
DEFAULT_CONTEXT_LENGTH = 131072


def _local_provider(config: dict, base_url: str) -> dict | None:
    """The custom_providers entry pointing at the LiteLLM gateway."""
    for provider in config.get("custom_providers") or []:
        if isinstance(provider, dict) and str(provider.get("url", "")).rstrip("/") == base_url.rstrip("/"):
            return provider
    return None


def sync_config(
    config_path: Path = DEFAULT_HERMES_CONFIG,
    base_url: str = DEFAULT_LITELLM_BASE,
    manifest_path: Path = DEFAULT_MANIFEST,
    exclude: set[str] = NON_CHAT_ALIASES,
) -> list[str]:
    """Rewrite the Hermes local provider's static models dict to LiteLLM's
    current local chat alias set (same exclusions as OpenCode). Existing
    per-alias context_length overrides are preserved; new aliases get
    DEFAULT_CONTEXT_LENGTH. Returns the alias list written.

    Hermes has a history of corrupt-config incidents (config.yaml.corrupt.*
    backups on this machine), so the write is atomic with a timestamped .bak.
    Round-trip drops YAML comments — the live file is machine-managed and
    comment-free (checked 2026-07-12).
    """
    if not config_path.exists():
        raise FileNotFoundError(f"{config_path} not found — is Hermes set up?")

    by_alias = {e.alias: e for e in load_manifest(manifest_path)}
    aliases = [
        mid
        for mid in fetch_model_ids(base_url)
        if mid not in exclude
        and not (by_alias.get(mid) is not None and by_alias[mid].is_cloud)
    ]

    config = yaml.safe_load(config_path.read_text()) or {}
    provider = _local_provider(config, base_url)
    if provider is None:
        raise ValueError(
            f"{config_path}: no custom_providers entry with url {base_url}"
        )
    old_models = provider.get("models") or {}
    provider["models"] = {
        alias: {
            "context_length": (old_models.get(alias) or {}).get(
                "context_length", DEFAULT_CONTEXT_LENGTH
            )
        }
        for alias in aliases
    }

    backup = config_path.with_suffix(f".yaml.presync.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    backup.write_text(config_path.read_text())
    tmp = config_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    os.replace(tmp, config_path)
    return aliases
