"""Provider registry — enumerates supported AI coding providers.

Mirrors the provider catalog in the original CodexBar Swift source:
- Sources/CodexBarCore/Models/ProviderDescriptor.swift
- Sources/CodexBarCore/Providers/ProviderStatus.swift

Each entry is a dict with:
    id          : canonical provider identifier (used in config.json)
    name        : human-readable display name
    auth_type   : one of "api_key", "cookie", "oauth", "builtin", "none"
    source_type : one of "api", "cookie", "jsonl", "dashboard", "builtin"
    status_url  : optional public status page URL
    env_vars    : optional list of environment variables that carry credentials
    linux       : whether Linux is a supported platform ("full", "partial", "none")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class FetchStrategy:
    kind: str


@dataclass(frozen=True)
class FetchPlan:
    source_modes: frozenset[str]
    strategies: tuple[FetchStrategy, ...]


@dataclass(frozen=True)
class ProviderMetadata:
    display_name: str


@dataclass(frozen=True)
class CliDescriptor:
    name: str


@dataclass(frozen=True)
class ProviderEntry:
    id: str
    name: str
    auth_type: str
    source_type: str
    status_url: Optional[str] = None
    env_vars: Optional[tuple[str, ...]] = None
    linux: str = "full"
    fetch_plan: FetchPlan = field(default_factory=lambda: FetchPlan(frozenset({"auto"}), ()))
    cli: Optional[CliDescriptor] = None

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(display_name=self.name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "auth_type": self.auth_type,
            "source_type": self.source_type,
            "status_url": self.status_url,
            "env_vars": list(self.env_vars) if self.env_vars else None,
            "linux": self.linux,
            "fetch_plan": {
                "source_modes": sorted(self.fetch_plan.source_modes),
                "strategies": [s.kind for s in self.fetch_plan.strategies],
            },
            "cli": self.cli.name if self.cli else None,
        }


def _plan(modes: Sequence[str], strategies: Sequence[str]) -> FetchPlan:
    return FetchPlan(
        source_modes=frozenset(modes),
        strategies=tuple(FetchStrategy(kind=s) for s in strategies),
    )


def _default_plan(source_type: str) -> FetchPlan:
    if source_type in {"api", "dashboard"}:
        return _plan(("auto", "api"), ("api",))
    if source_type in {"cookie", "jsonl"}:
        return _plan(("auto", "web", "local"), ("web", "local"))
    if source_type == "builtin":
        return _plan(("auto", "local"), ("local",))
    return _plan(("auto",), ("api",))


def _entry(**kwargs: Any) -> ProviderEntry:
    """Convenience constructor with env_vars as a tuple."""
    if "env_vars" in kwargs and isinstance(kwargs["env_vars"], list):
        kwargs["env_vars"] = tuple(kwargs["env_vars"])
    if "fetch_plan" not in kwargs:
        kwargs["fetch_plan"] = _default_plan(kwargs.get("source_type", "api"))
    if "cli" in kwargs and isinstance(kwargs["cli"], str):
        kwargs["cli"] = CliDescriptor(name=kwargs["cli"])
    return ProviderEntry(**kwargs)  # type: ignore[arg-type]


ALL_PROVIDERS: tuple[ProviderEntry, ...] = (
    _entry(
        id="codex", name="Codex",
        auth_type="api_key", source_type="api",
        status_url="https://status.openai.com",
        env_vars=("CODEXBAR_CODEX_API_KEY", "OPENAI_ADMIN_KEY", "OPENAI_API_KEY"),
        fetch_plan=_plan(("auto", "cli", "local"), ("cli", "local")),
        cli="codex",
    ),
    _entry(
        id="openai", name="OpenAI",
        auth_type="api_key", source_type="api",
        status_url="https://status.openai.com",
        env_vars=("OPENAI_ADMIN_KEY", "OPENAI_API_KEY"),
    ),
    _entry(
        id="claude", name="Claude",
        auth_type="api_key", source_type="api",
        status_url="https://status.anthropic.com",
        env_vars=("ANTHROPIC_ADMIN_KEY", "ANTHROPIC_API_KEY"),
        fetch_plan=_plan(("auto", "api", "local"), ("api", "local")),
        cli="claude",
    ),
    _entry(
        id="gemini", name="Gemini",
        auth_type="api_key", source_type="api",
        status_url="https://status.cloud.google.com",
        env_vars=("GEMINI_API_KEY",),
    ),
    _entry(
        id="copilot", name="GitHub Copilot",
        auth_type="cookie", source_type="cookie",
        status_url="https://www.githubstatus.com",
        env_vars=("GITHUB_TOKEN", "COPILOT_API_TOKEN"),
    ),
    _entry(
        id="cursor", name="Cursor",
        auth_type="cookie", source_type="cookie",
        env_vars=("CURSOR_TOKEN",),
    ),
    _entry(
        id="windsurf", name="Windsurf",
        auth_type="cookie", source_type="cookie",
        env_vars=("WINDSURF_TOKEN",),
    ),
    _entry(
        id="zed", name="Zed",
        auth_type="cookie", source_type="cookie",
        env_vars=("ZED_TOKEN",),
    ),
    _entry(
        id="jetbrains", name="JetBrains AI",
        auth_type="api_key", source_type="api",
        env_vars=("JETBRAINS_API_KEY",),
    ),
    _entry(
        id="opencode", name="OpenCode",
        auth_type="api_key", source_type="api",
        env_vars=("OPENCODE_API_KEY",),
    ),
    _entry(
        id="kiro", name="Kiro",
        auth_type="cookie", source_type="cookie",
        env_vars=("KIRO_TOKEN",),
    ),
    _entry(
        id="augment", name="Augment",
        auth_type="api_key", source_type="api",
        env_vars=("AUGMENT_API_KEY",),
    ),
    _entry(
        id="amp", name="Amp",
        auth_type="api_key", source_type="api",
        env_vars=("AMP_API_KEY",),
    ),
    _entry(
        id="zai", name="z.ai",
        auth_type="api_key", source_type="api",
        env_vars=("Z_AI_API_KEY",),
    ),
    _entry(
        id="deepseek", name="DeepSeek",
        auth_type="api_key", source_type="api",
        env_vars=("DEEPSEEK_API_KEY", "DEEPSEEK_KEY"),
    ),
    _entry(
        id="grok", name="Grok",
        auth_type="api_key", source_type="api",
        linux="partial",
    ),
    _entry(
        id="moonshot", name="Moonshot",
        auth_type="api_key", source_type="api",
        env_vars=("MOONSHOT_API_KEY",),
    ),
    _entry(
        id="venice", name="Venice",
        auth_type="api_key", source_type="api",
        env_vars=("VENICE_API_KEY",),
    ),
    _entry(
        id="openrouter", name="OpenRouter",
        auth_type="api_key", source_type="api",
        env_vars=("OPENROUTER_API_KEY",),
    ),
    _entry(
        id="groq", name="GroqCloud",
        auth_type="api_key", source_type="api",
        env_vars=("GROQ_API_KEY",),
    ),
    _entry(
        id="elevenlabs", name="ElevenLabs",
        auth_type="api_key", source_type="api",
        env_vars=("ELEVENLABS_API_KEY",),
    ),
    _entry(
        id="warp", name="Warp",
        auth_type="api_key", source_type="api",
        env_vars=("WARP_API_KEY",),
    ),
    _entry(
        id="poe", name="Poe",
        auth_type="api_key", source_type="api",
        env_vars=("POE_API_KEY",),
    ),
    _entry(
        id="chutes", name="Chutes",
        auth_type="api_key", source_type="api",
        env_vars=("CHUTES_API_KEY",),
    ),
    _entry(
        id="codebuff", name="Codebuff",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="croft", name="Croft",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="alibaba", name="Alibaba Coding",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="alibabatokenplan", name="Alibaba Token",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="minimax", name="MiniMax",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="kimi", name="Kimi",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="kimik2", name="Kimi K2",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="kilo", name="Kilo",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="doubao", name="Doubao",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="synthetic", name="Synthetic",
        auth_type="none", source_type="builtin",
    ),
    _entry(
        id="crossmodel", name="CrossModel",
        auth_type="none", source_type="builtin",
    ),
    _entry(
        id="manus", name="Manus",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="llmproxy", name="LLM Proxy",
        auth_type="api_key", source_type="api",
        env_vars=("LLM_PROXY_API_KEY",),
    ),
    _entry(
        id="litellm", name="LiteLLM",
        auth_type="api_key", source_type="api",
        env_vars=("LITELLM_API_KEY",),
    ),
    _entry(
        id="clawrouter", name="ClawRouter",
        auth_type="api_key", source_type="api",
        env_vars=("CLAWROUTER_API_KEY",),
    ),
    _entry(
        id="deepgram", name="Deepgram",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="azureopenai", name="Azure OpenAI",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="bedrock", name="AWS Bedrock",
        auth_type="oauth", source_type="api",
    ),
    _entry(
        id="vertexai", name="Vertex AI",
        auth_type="oauth", source_type="api",
    ),
    _entry(
        id="antigravity", name="Antigravity",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="ollama", name="Ollama",
        auth_type="none", source_type="builtin",
    ),
    _entry(
        id="perplexity", name="Perplexity",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="mistral", name="Mistral",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="abacus", name="Abacus AI",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="sakana", name="Sakana AI",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="stepfun", name="StepFun",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="qoder", name="Qoder",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="devin", name="Devin",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="commandcode", name="Command Code",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="t3chat", name="T3 Chat",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="mimo", name="MiMo",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="factory", name="Factory",
        auth_type="api_key", source_type="api",
    ),
    _entry(
        id="opencodego", name="OpenCode Go",
        auth_type="api_key", source_type="api",
    ),
)


def all_providers() -> tuple[ProviderEntry, ...]:
    """Return the full provider catalog."""
    return ALL_PROVIDERS


def provider_by_id(provider_id: str) -> Optional[ProviderEntry]:
    """Look up a provider entry by canonical ID."""
    for p in ALL_PROVIDERS:
        if p.id == provider_id:
            return p
    return None


def provider_ids() -> list[str]:
    """Return canonical IDs for all registered providers, in order."""
    return [p.id for p in ALL_PROVIDERS]


def enabled_provider_ids(config: Any) -> list[str]:
    """Return IDs of providers marked enabled in the config.

    Falls back to the full catalog when no config is available.
    """
    if config is None:
        return provider_ids()
    enabled = []
    for p in ALL_PROVIDERS:
        if p.id in config:
            enabled.append(p.id)
    return enabled


def auth_types() -> list[str]:
    """Return unique auth types present in the catalog."""
    return sorted({p.auth_type for p in ALL_PROVIDERS})
