"""Tests for codexbar_usage.registry — provider catalog enumeration and lookup."""

from __future__ import annotations

import pytest

from codexbar_usage.registry import (
    ALL_PROVIDERS,
    ProviderEntry,
    all_providers,
    auth_types,
    provider_by_id,
    provider_ids,
)


# ---------------------------------------------------------------------------
# Test: all_providers returns the full catalog
# ---------------------------------------------------------------------------

def test_all_providers_returns_tuple():
    result = all_providers()
    assert isinstance(result, tuple)
    assert len(result) > 0


def test_all_providers_matches_ALL_PROVIDERS():
    assert all_providers() is ALL_PROVIDERS


# ---------------------------------------------------------------------------
# Test: provider count
# ---------------------------------------------------------------------------

def test_provider_count():
    """The registry should have at least 50 providers."""
    assert len(ALL_PROVIDERS) >= 50


# ---------------------------------------------------------------------------
# Test: provider_by_id — lookup
# ---------------------------------------------------------------------------

def test_provider_by_id_found():
    entry = provider_by_id("claude")
    assert entry is not None
    assert entry.id == "claude"
    assert entry.name == "Claude"
    assert entry.auth_type == "api_key"


def test_provider_by_id_not_found():
    entry = provider_by_id("nonexistent-provider-xyz")
    assert entry is None


def test_provider_by_id_all_unique_ids():
    """Every provider ID should be uniquely findable."""
    seen = set()
    for entry in ALL_PROVIDERS:
        found = provider_by_id(entry.id)
        assert found is not None, f"provider_by_id({entry.id}) returned None"
        assert found.id == entry.id
        assert entry.id not in seen, f"duplicate ID: {entry.id}"
        seen.add(entry.id)


# ---------------------------------------------------------------------------
# Test: provider_ids
# ---------------------------------------------------------------------------

def test_provider_ids_returns_list():
    ids = provider_ids()
    assert isinstance(ids, list)
    assert len(ids) == len(ALL_PROVIDERS)


def test_provider_ids_contains_expected():
    ids = provider_ids()
    for expected in ("openai", "claude", "gemini", "copilot", "deepseek",
                      "grok", "openrouter", "litellm"):
        assert expected in ids


def test_provider_ids_no_duplicates():
    ids = provider_ids()
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Test: ProviderEntry fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("provider_id,expected_name", [
    ("openai", "OpenAI"),
    ("claude", "Claude"),
    ("gemini", "Gemini"),
    ("copilot", "GitHub Copilot"),
    ("deepseek", "DeepSeek"),
    ("grok", "Grok"),
    ("openrouter", "OpenRouter"),
    ("litellm", "LiteLLM"),
])
def test_provider_entry_names(provider_id: str, expected_name: str):
    entry = provider_by_id(provider_id)
    assert entry is not None
    assert entry.name == expected_name


@pytest.mark.parametrize("provider_id,expected_auth", [
    ("openai", "api_key"),
    ("claude", "api_key"),
    ("copilot", "cookie"),
    ("bedrock", "oauth"),
    ("ollama", "none"),
    ("synthetic", "none"),
])
def test_provider_entry_auth_types(provider_id: str, expected_auth: str):
    entry = provider_by_id(provider_id)
    assert entry is not None
    assert entry.auth_type == expected_auth


# ---------------------------------------------------------------------------
# Test: linux support field
# ---------------------------------------------------------------------------

def test_grok_linux_partial():
    entry = provider_by_id("grok")
    assert entry is not None
    assert entry.linux == "partial"


def test_major_providers_linux_full():
    for pid in ("openai", "claude", "gemini", "deepseek", "copilot",
                "openrouter", "litellm"):
        entry = provider_by_id(pid)
        assert entry is not None
        assert entry.linux == "full"


# ---------------------------------------------------------------------------
# Test: auth_types helper
# ---------------------------------------------------------------------------

def test_auth_types_returns_sorted_unique():
    types = auth_types()
    assert isinstance(types, list)
    assert types == sorted(set(types))


def test_auth_types_contains_expected():
    types = auth_types()
    assert "api_key" in types
    assert "cookie" in types
    assert "oauth" in types
    assert "none" in types


# ---------------------------------------------------------------------------
# Test: to_dict serialization
# ---------------------------------------------------------------------------

def test_provider_entry_to_dict():
    entry = provider_by_id("claude")
    assert entry is not None
    d = entry.to_dict()
    assert d["id"] == "claude"
    assert d["name"] == "Claude"
    assert d["auth_type"] == "api_key"
    assert "linux" in d
    assert d["linux"] == "full"


def test_provider_entry_to_dict_with_env_vars():
    entry = provider_by_id("openai")
    assert entry is not None
    d = entry.to_dict()
    assert d["env_vars"] is not None
    assert "OPENAI_ADMIN_KEY" in d["env_vars"]
    assert "OPENAI_API_KEY" in d["env_vars"]


def test_provider_entry_to_dict_without_env_vars():
    entry = provider_by_id("codebuff")
    assert entry is not None
    d = entry.to_dict()
    assert d["env_vars"] is None


# ---------------------------------------------------------------------------
# Test: status_url
# ---------------------------------------------------------------------------

def test_providers_with_status_url():
    for pid in ("openai", "claude", "gemini"):
        entry = provider_by_id(pid)
        assert entry is not None
        assert entry.status_url is not None
        assert entry.status_url.startswith("https://")


def test_grok_no_status_url():
    entry = provider_by_id("grok")
    assert entry is not None
    assert entry.status_url is None


# ---------------------------------------------------------------------------
# Test: ProviderEntry is frozen (immutable)
# ---------------------------------------------------------------------------

def test_provider_entry_is_frozen():
    entry = ALL_PROVIDERS[0]
    with pytest.raises((TypeError, Exception)):
        entry.id = "modified"
