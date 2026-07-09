"""Resolve provider aliases to LiteLLM provider identifiers."""

from __future__ import annotations

_PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "azure": "azure",
    "ollama": "ollama",
    "lemonade": "ollama",
    "vllm": "vllm",
    "qwen": "ollama",
    "gemini": "gemini",
}


def canonical_provider(alias: str) -> str | None:
    """Return the canonical LiteLLM provider name for *alias*, or None."""
    return _PROVIDER_ALIASES.get(alias.lower())
