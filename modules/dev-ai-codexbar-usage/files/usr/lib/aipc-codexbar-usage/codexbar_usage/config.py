"""Configuration management for CodexBar-style provider tracking.

Reads/writes ~/.config/codexbar/config.json (XDG-compliant), supports
environment variable overrides, and provides provider enable/disable
and API key management — matching the CodexBar config schema.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG_DIR = Path.home() / ".config" / "codexbar"
LEGACY_CONFIG_DIR = Path.home() / ".codexbar"
CONFIG_FILENAME = "config.json"


@dataclass
class TokenAccount:
    id: str
    label: str
    token: str
    added_at: int = 0
    last_used: int = 0


@dataclass
class ProviderConfig:
    id: str
    enabled: bool = True
    source: str = "auto"
    cookie_source: str = "auto"
    cookie_header: Optional[str] = None
    api_key: Optional[str] = None
    enterprise_host: Optional[str] = None
    region: Optional[str] = None
    workspace_id: Optional[str] = None
    token_accounts: Optional[List[Dict[str, Any]]] = None


@dataclass
class CodexBarConfig:
    version: int = 1
    providers: List[ProviderConfig] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "providers": [asdict(p) for p in self.providers],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodexBarConfig":
        providers = [
            ProviderConfig(
                id=p.get("id", "unknown"),
                enabled=p.get("enabled", True),
                source=p.get("source", "auto"),
                cookie_source=p.get("cookie_source", "auto"),
                cookie_header=p.get("cookie_header"),
                api_key=p.get("apiKey") or p.get("api_key"),
                enterprise_host=p.get("enterpriseHost") or p.get("enterprise_host"),
                region=p.get("region"),
                workspace_id=p.get("workspaceID") or p.get("workspace_id"),
                token_accounts=p.get("tokenAccounts") or p.get("token_accounts"),
            )
            for p in data.get("providers", [])
        ]
        return cls(version=data.get("version", 1), providers=providers)


def _resolve_config_dir() -> Path:
    env_path = os.environ.get("CODEXBAR_CONFIG")
    if env_path:
        return Path(env_path)
    if os.environ.get("XDG_CONFIG_HOME"):
        xdg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "codexbar"
        if xdg_dir.exists():
            return xdg_dir
        return xdg_dir
    legacy = LEGACY_CONFIG_DIR / CONFIG_FILENAME
    if legacy.exists():
        return LEGACY_CONFIG_DIR
    return DEFAULT_CONFIG_DIR


def config_path() -> Path:
    return _resolve_config_dir() / CONFIG_FILENAME


def load_config() -> CodexBarConfig:
    path = config_path()
    if not path.exists():
        return CodexBarConfig()
    try:
        data = json.loads(path.read_text())
        return CodexBarConfig.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return CodexBarConfig()


def save_config(config: CodexBarConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)


def get_provider_config(config: CodexBarConfig, provider_id: str) -> Optional[ProviderConfig]:
    for p in config.providers:
        if p.id == provider_id:
            return p
    return None


def upsert_provider_config(config: CodexBarConfig, provider_id: str) -> ProviderConfig:
    for i, p in enumerate(config.providers):
        if p.id == provider_id:
            config.providers[i] = ProviderConfig(
                id=p.id,
                enabled=p.enabled,
                source=p.source,
                cookie_source=p.cookie_source,
                cookie_header=p.cookie_header,
                api_key=p.api_key,
                enterprise_host=p.enterprise_host,
                region=p.region,
                workspace_id=p.workspace_id,
                token_accounts=p.token_accounts,
            )
            return config.providers[i]
    new_p = ProviderConfig(id=provider_id)
    config.providers.append(new_p)
    return new_p


def toggle_provider(config: CodexBarConfig, provider_id: str, enabled: bool) -> bool:
    p = get_provider_config(config, provider_id)
    if p is None:
        p = upsert_provider_config(config, provider_id)
    p.enabled = enabled
    save_config(config)
    return True


def set_api_key(config: CodexBarConfig, provider_id: str, api_key: str) -> bool:
    p = upsert_provider_config(config, provider_id)
    p.api_key = api_key
    save_config(config)
    return True


def resolve_api_key(provider_id: str) -> Optional[str]:
    """Resolve API key: config file → CODEXBAR_<PROVIDER>_API_KEY env → env fallbacks."""
    config = load_config()
    p = get_provider_config(config, provider_id)
    if p and p.api_key:
        return p.api_key

    env_upper = provider_id.upper().replace("-", "_")
    env_key = f"CODEXBAR_{env_upper}_API_KEY"
    env_val = os.environ.get(env_key)
    if env_val:
        return env_val

    _FALLBACK_ENV = {
        "openai": ("OPENAI_ADMIN_KEY", "OPENAI_API_KEY"),
        "claude": ("ANTHROPIC_ADMIN_KEY", "ANTHROPIC_API_KEY"),
        "gemini": ("GEMINI_API_KEY",),
        "copilot": ("GITHUB_TOKEN", "COPILOT_API_TOKEN"),
        "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_KEY"),
        "moonshot": ("MOONSHOT_API_KEY",),
        "openrouter": ("OPENROUTER_API_KEY",),
        "groq": ("GROQ_API_KEY",),
        "elevenlabs": ("ELEVENLABS_API_KEY",),
        "zai": ("Z_AI_API_KEY",),
        "venice": ("VENICE_API_KEY",),
        "warp": ("WARP_API_KEY",),
        "poe": ("POE_API_KEY",),
        "chutes": ("CHUTES_API_KEY",),
        "litellm": ("LITELLM_API_KEY",),
        "llmproxy": ("LLM_PROXY_API_KEY",),
        "clawrouter": ("CLAWROUTER_API_KEY",),
    }
    for fallback in _FALLBACK_ENV.get(provider_id, ()):
        val = os.environ.get(fallback)
        if val:
            return val
    return None


def config_validate() -> List[str]:
    errors: List[str] = []
    path = config_path()
    if not path.exists():
        errors.append(f"Config file not found: {path}")
        return errors
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON: {e}")
        return errors
    if not isinstance(data, dict):
        errors.append("Config root must be an object")
        return errors
    if "version" in data and not isinstance(data["version"], int):
        errors.append("'version' must be an integer")
    if "providers" in data:
        if not isinstance(data["providers"], list):
            errors.append("'providers' must be an array")
        else:
            for i, prov in enumerate(data["providers"]):
                if not isinstance(prov, dict):
                    errors.append(f"providers[{i}] must be an object")
                    continue
                if "id" not in prov:
                    errors.append(f"providers[{i}] missing required 'id' field")
    return errors
