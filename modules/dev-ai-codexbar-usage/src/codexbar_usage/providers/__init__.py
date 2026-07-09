"""Provider package — concrete fetchers for AI coding usage sources.

Import concrete classes via :func:`get_provider_class` so callers never need
to know the module file name (e.g. ``codex`` → ``openai_codex``).
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Optional, Type

from codexbar_usage.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Canonical provider id → submodule name under this package.
PROVIDER_MODULE_MAP: dict[str, str] = {
    "codex": "openai_codex",
    "openai": "openai",
    "claude": "claude",
    "gemini": "gemini",
    "copilot": "copilot",
    "cursor": "cursor",
    "windsurf": "windsurf",
    "zed": "zed",
    "deepseek": "deepseek",
    "moonshot": "moonshot",
    "kimi": "kimi",
    "openrouter": "openrouter",
    "grok": "grok",
    "warp": "warp",
    "litellm": "litellm",
}


def get_provider_class(provider_id: str) -> Optional[Type[BaseProvider]]:
    """Return the BaseProvider subclass for *provider_id*, or None."""
    mod_name = PROVIDER_MODULE_MAP.get(provider_id)
    if not mod_name:
        return None
    try:
        mod = importlib.import_module(f"codexbar_usage.providers.{mod_name}")
    except ImportError as exc:
        logger.debug("provider module %s not importable: %s", mod_name, exc)
        return None

    candidates: list[Type[BaseProvider]] = []
    for attr_name in dir(mod):
        obj = getattr(mod, attr_name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseProvider)
            and obj is not BaseProvider
        ):
            candidates.append(obj)

    if not candidates:
        return None

    # Prefer *Provider named after the module when multiple exist.
    preferred = next(
        (c for c in candidates if c.__name__.lower().endswith("provider")),
        candidates[0],
    )
    return preferred


def instantiate_provider(
    provider_id: str,
    api_key: Optional[str] = None,
    config: Optional[dict[str, Any]] = None,
    **extra: Any,
) -> Optional[BaseProvider]:
    """Construct a provider instance. Returns None if no fetcher exists."""
    cls = get_provider_class(provider_id)
    if cls is None:
        return None

    kwargs: dict[str, Any] = {"api_key": api_key}
    if config is not None:
        kwargs["config"] = config
    kwargs.update(extra)

    try:
        return cls(**kwargs)
    except TypeError:
        # Some providers take fewer kwargs.
        try:
            return cls(api_key=api_key)
        except TypeError:
            logger.warning("could not instantiate provider %s", provider_id)
            return None


__all__ = [
    "BaseProvider",
    "PROVIDER_MODULE_MAP",
    "get_provider_class",
    "instantiate_provider",
]
