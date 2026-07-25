from __future__ import annotations

import os
import time
from pathlib import Path

import yaml

from aipc_lib.models import DEFAULT_MANIFEST, load_manifest
from aipc_lib.opencode_sync import DEFAULT_LITELLM_BASE, NON_CHAT_ALIASES, fetch_model_ids

DEFAULT_HERMES_HOME = Path.home() / ".hermes"
DEFAULT_HERMES_CONFIG = DEFAULT_HERMES_HOME / "config.yaml"
DEFAULT_CONTEXT_LENGTH = 131072
CLIPROXY_CONTEXT_LENGTH = 200000


def _local_provider(config: dict, base_url: str) -> dict | None:
    """The custom_providers entry pointing at the LiteLLM gateway."""
    for provider in config.get("custom_providers") or []:
        if not isinstance(provider, dict):
            continue
        url = provider.get("base_url") or provider.get("url") or ""
        if str(url).rstrip("/") == base_url.rstrip("/"):
            return provider
    return None


def _mirror_claude_aliases(config: dict, aliases: list[str]) -> None:
    """Give the direct-CLIProxy providers the same claude-* set as the gateway.

    Those providers bypass LiteLLM (`api_mode: anthropic_messages` straight at
    :8317) and their model lists are otherwise hand-maintained, which is how
    `claude-opus-5` went missing from the profile the desktop actually runs.
    Additive only — they also serve gpt-5.x aliases the gateway doesn't list.
    """
    claude = [alias for alias in aliases if alias.startswith("claude-")]
    for provider in config.get("custom_providers") or []:
        if not isinstance(provider, dict) or "cliproxy" not in str(provider.get("name", "")):
            continue
        models = provider.setdefault("models", {})
        for alias in claude:
            models.setdefault(alias, {"context_length": CLIPROXY_CONTEXT_LENGTH})


def config_paths(home: Path = DEFAULT_HERMES_HOME) -> list[Path]:
    """Every Hermes config on this machine, default profile first.

    A Hermes profile is a whole separate HERMES_HOME under ``profiles/<name>/``
    with its own full ``custom_providers`` block — nothing is inherited from
    the top-level config. Syncing only the top-level file silently misses the
    profile the user actually runs (cost us an hour on 2026-07-26).
    """
    paths = [home / "config.yaml"]
    paths += sorted(p / "config.yaml" for p in (home / "profiles").glob("*") if p.is_dir())
    return [p for p in paths if p.exists()]


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

    _mirror_claude_aliases(config, aliases)

    backup = config_path.with_suffix(f".yaml.presync.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    backup.write_text(config_path.read_text())
    tmp = config_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    os.replace(tmp, config_path)
    return aliases


def sync_all(home: Path = DEFAULT_HERMES_HOME, **kwargs) -> list[str]:
    """Sync every Hermes config under ``home`` (default profile + profiles/*).

    Configs without a LiteLLM provider entry are skipped rather than fatal —
    a profile may legitimately point elsewhere. Raises when no config could be
    synced at all, so `aipc providers sync` reports hermes as SKIPPED.
    """
    paths = config_paths(home)
    if not paths:
        raise FileNotFoundError(f"{home}: no config.yaml found — is Hermes set up?")
    synced: list[str] = []
    errors: list[str] = []
    for path in paths:
        try:
            synced = sync_config(config_path=path, **kwargs)
        except ValueError as e:
            errors.append(str(e))
    if not synced and errors:
        raise ValueError("; ".join(errors))
    return synced
