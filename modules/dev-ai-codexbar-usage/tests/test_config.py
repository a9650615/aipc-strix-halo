"""Tests for codexbar_usage.config — read/write, enable/disable, API key, env override."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Generator

import pytest

from codexbar_usage.config import (
    CodexBarConfig,
    ProviderConfig,
    config_path,
    config_validate,
    config_validate as config_validate_fn,
    load_config,
    resolve_api_key,
    save_config,
    set_api_key,
    toggle_provider,
    upsert_provider_config,
    get_provider_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_codexbar_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Remove all CODEXBAR_* env vars and CODEXBAR_CONFIG to get a clean env."""
    for key in list(os.environ.keys()):
        if key.startswith("CODEXBAR_") or key.startswith("OPENAI_") or \
           key.startswith("ANTHROPIC_") or key.startswith("GEMINI_") or \
           key.startswith("DEEPSEEK_") or key.startswith("GITHUB_") or \
           key == "XDG_CONFIG_HOME":
            monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary config directory and point CODEXBAR_CONFIG at it."""
    config_dir = tmp_path / "codexbar"
    config_dir.mkdir()
    monkeypatch.setenv("CODEXBAR_CONFIG", str(config_dir))
    return config_dir


@pytest.fixture
def config_dir_with_file(tmp_config_dir: Path) -> Path:
    """Config directory with a valid config.json pre-created."""
    sample = CodexBarConfig(
        version=1,
        providers=[
            ProviderConfig(id="claude", enabled=True, api_key="sk-ant-test-123"),
            ProviderConfig(id="openai", enabled=False, api_key=None),
        ],
    )
    save_config(sample)
    return tmp_config_dir


# ---------------------------------------------------------------------------
# Test: load_config — no file → default empty config
# ---------------------------------------------------------------------------

def test_load_config_no_file(tmp_config_dir: Path):
    path = config_path()
    assert not path.exists()
    cfg = load_config()
    assert cfg.version == 1
    assert cfg.providers == []


# ---------------------------------------------------------------------------
# Test: save_config writes valid JSON with correct permissions
# ---------------------------------------------------------------------------

def test_save_config_writes_json(tmp_config_dir: Path):
    cfg = CodexBarConfig(
        version=1,
        providers=[ProviderConfig(id="claude", enabled=True)],
    )
    save_config(cfg)

    path = config_path()
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["version"] == 1
    assert len(data["providers"]) == 1
    assert data["providers"][0]["id"] == "claude"


def test_save_config_file_permissions(tmp_config_dir: Path):
    cfg = CodexBarConfig()
    save_config(cfg)
    mode = config_path().stat().st_mode
    assert mode & 0o777 == 0o600


def test_save_config_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """save_config should mkdir -p the parent directory."""
    deep = tmp_path / "a" / "b" / "c" / "codexbar"
    monkeypatch.setenv("CODEXBAR_CONFIG", str(deep))
    cfg = CodexBarConfig()
    save_config(cfg)
    assert config_path().parent.exists()


# ---------------------------------------------------------------------------
# Test: load_config — reads existing file
# ---------------------------------------------------------------------------

def test_load_config_reads_existing(config_dir_with_file: Path):
    cfg = load_config()
    assert cfg.version == 1
    assert len(cfg.providers) == 2
    claude = get_provider_config(cfg, "claude")
    assert claude is not None
    assert claude.enabled is True
    assert claude.api_key == "sk-ant-test-123"


# ---------------------------------------------------------------------------
# Test: load_config — handles invalid JSON gracefully
# ---------------------------------------------------------------------------

def test_load_config_invalid_json(tmp_config_dir: Path):
    config_path().write_text("{not valid json")
    cfg = load_config()
    assert cfg.providers == []


# ---------------------------------------------------------------------------
# Test: toggle_provider — enable/disable
# ---------------------------------------------------------------------------

def test_toggle_provider_enable(tmp_config_dir: Path):
    cfg = CodexBarConfig()
    toggle_provider(cfg, "claude", True)
    claude = get_provider_config(cfg, "claude")
    assert claude is not None
    assert claude.enabled is True


def test_toggle_provider_disable(tmp_config_dir: Path):
    cfg = CodexBarConfig(
        providers=[ProviderConfig(id="claude", enabled=True)],
    )
    toggle_provider(cfg, "claude", False)
    claude = get_provider_config(cfg, "claude")
    assert claude.enabled is False


def test_toggle_provider_persists(tmp_config_dir: Path):
    cfg = CodexBarConfig()
    toggle_provider(cfg, "gemini", True)
    reloaded = load_config()
    gemini = get_provider_config(reloaded, "gemini")
    assert gemini is not None
    assert gemini.enabled is True


# ---------------------------------------------------------------------------
# Test: set_api_key
# ---------------------------------------------------------------------------

def test_set_api_key(tmp_config_dir: Path):
    cfg = CodexBarConfig()
    result = set_api_key(cfg, "claude", "sk-ant-secret-456")
    assert result is True
    claude = get_provider_config(cfg, "claude")
    assert claude is not None
    assert claude.api_key == "sk-ant-secret-456"


def test_set_api_key_upserts_new_provider(tmp_config_dir: Path):
    cfg = CodexBarConfig()
    set_api_key(cfg, "deepseek", "sk-ds-789")
    deepseek = get_provider_config(cfg, "deepseek")
    assert deepseek is not None
    assert deepseek.api_key == "sk-ds-789"


def test_set_api_key_overwrites_existing(tmp_config_dir: Path):
    cfg = CodexBarConfig(
        providers=[ProviderConfig(id="claude", api_key="old-key")],
    )
    set_api_key(cfg, "claude", "new-key")
    claude = get_provider_config(cfg, "claude")
    assert claude.api_key == "new-key"


# ---------------------------------------------------------------------------
# Test: resolve_api_key — config → env → fallback
# ---------------------------------------------------------------------------

def test_resolve_api_key_from_config(tmp_config_dir: Path):
    cfg = CodexBarConfig(
        providers=[ProviderConfig(id="claude", api_key="sk-ant-from-config")],
    )
    save_config(cfg)
    key = resolve_api_key("claude")
    assert key == "sk-ant-from-config"


def test_resolve_api_key_from_env(monkeypatch: pytest.MonkeyPatch, tmp_config_dir: Path):
    monkeypatch.setenv("CODEXBAR_CLAUDE_API_KEY", "sk-ant-from-env")
    key = resolve_api_key("claude")
    assert key == "sk-ant-from-env"


def test_resolve_api_key_config_takes_priority(
    tmp_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = CodexBarConfig(
        providers=[ProviderConfig(id="claude", api_key="sk-ant-from-config")],
    )
    save_config(cfg)
    monkeypatch.setenv("CODEXBAR_CLAUDE_API_KEY", "sk-ant-from-env")
    key = resolve_api_key("claude")
    assert key == "sk-ant-from-config"


def test_resolve_api_key_fallback_env(monkeypatch: pytest.MonkeyPatch, tmp_config_dir: Path):
    """When CODEXBAR_CLAUDE_API_KEY is not set, fall back to ANTHROPIC_API_KEY."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fallback")
    key = resolve_api_key("claude")
    assert key == "sk-ant-fallback"


def test_resolve_api_key_not_found(tmp_config_dir: Path):
    key = resolve_api_key("nonexistent-provider")
    assert key is None


# ---------------------------------------------------------------------------
# Test: config_validate
# ---------------------------------------------------------------------------

def test_config_validate_no_file(tmp_config_dir: Path):
    errors = config_validate_fn()
    assert len(errors) == 1
    assert "not found" in errors[0].lower()


def test_config_validate_valid(tmp_config_dir: Path):
    save_config(CodexBarConfig(providers=[ProviderConfig(id="claude")]))
    errors = config_validate_fn()
    assert errors == []


def test_config_validate_invalid_json(tmp_config_dir: Path):
    config_path().write_text("{broken")
    errors = config_validate_fn()
    assert len(errors) == 1
    assert "json" in errors[0].lower()


def test_config_validate_missing_provider_id(tmp_config_dir: Path):
    config_path().write_text(json.dumps({"version": 1, "providers": [{"enabled": True}]}))
    errors = config_validate_fn()
    assert any("id" in e for e in errors)


def test_config_validate_non_object_root(tmp_config_dir: Path):
    config_path().write_text(json.dumps([1, 2, 3]))
    errors = config_validate_fn()
    assert any("object" in e.lower() for e in errors)


def test_config_validate_non_integer_version(tmp_config_dir: Path):
    config_path().write_text(json.dumps({"version": "one", "providers": []}))
    errors = config_validate_fn()
    assert any("version" in e and "integer" in e for e in errors)


# ---------------------------------------------------------------------------
# Test: CodexBarConfig round-trip
# ---------------------------------------------------------------------------

def test_config_roundtrip():
    original = CodexBarConfig(
        version=1,
        providers=[
            ProviderConfig(id="claude", enabled=True, api_key="sk-ant-test"),
            ProviderConfig(id="openai", enabled=False, api_key="sk-openai-test"),
        ],
    )
    as_dict = original.to_dict()
    restored = CodexBarConfig.from_dict(as_dict)
    assert restored.version == original.version
    assert len(restored.providers) == len(original.providers)
    assert restored.providers[0].id == "claude"
    assert restored.providers[0].api_key == "sk-ant-test"
    assert restored.providers[1].enabled is False


def test_config_from_dict_flexible_keys():
    """from_dict should accept both snake_case and camelCase keys."""
    raw = {
        "version": 1,
        "providers": [
            {
                "id": "claude",
                "apiKey": "sk-ant-admin-xxx",
                "enterpriseHost": "enterprise.anthropic.com",
                "workspaceID": "ws-123",
            }
        ],
    }
    cfg = CodexBarConfig.from_dict(raw)
    claude = cfg.providers[0]
    assert claude.api_key == "sk-ant-admin-xxx"
    assert claude.enterprise_host == "enterprise.anthropic.com"
    assert claude.workspace_id == "ws-123"


# ---------------------------------------------------------------------------
# Test: upsert_provider_config
# ---------------------------------------------------------------------------

def test_upsert_provider_config_new():
    cfg = CodexBarConfig()
    new = upsert_provider_config(cfg, "new-provider")
    assert new.id == "new-provider"
    assert new.enabled is True
    assert len(cfg.providers) == 1


def test_upsert_provider_config_existing():
    cfg = CodexBarConfig(
        providers=[ProviderConfig(id="claude", enabled=True, api_key="key1")],
    )
    updated = upsert_provider_config(cfg, "claude")
    assert updated.api_key == "key1"  # preserved
    assert len(cfg.providers) == 1
