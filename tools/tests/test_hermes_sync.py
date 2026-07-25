from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from aipc_lib import hermes_sync


@pytest.fixture()
def manifest(tmp_path: Path) -> Path:
    p = tmp_path / "models.yaml"
    p.write_text(
        textwrap.dedent(
            """\
            models:
              - alias: coder-agentic
                backend: lemonade
                model_id: Q36
                size_gb: 21.8
              - alias: coder-122b
                backend: lemonade
                model_id: Q122
                size_gb: 59.2
              - alias: main-cloud
                backend: anthropic
                model_id: claude
                size_gb: cloud
            """
        )
    )
    return p


@pytest.fixture()
def hermes_config(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "model": {"default": "coder-agentic", "provider": "custom:local"},
                "custom_providers": [
                    {
                        "name": "local",
                        "base_url": "http://127.0.0.1:4000",
                        "api_key": "aipc-local",
                        "models": {
                            "coder-agentic": {"context_length": 131072},
                            "stale-old-alias": {"context_length": 32768},
                        },
                    }
                ],
            },
            sort_keys=False,
        )
    )
    return p


def test_sync_rewrites_models_and_preserves_overrides(
    hermes_config: Path, manifest: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        hermes_sync,
        "fetch_model_ids",
        lambda base_url: ["coder-agentic", "coder-122b", "main-cloud", "embed-bge"],
    )
    aliases = hermes_sync.sync_config(
        config_path=hermes_config, manifest_path=manifest
    )
    # cloud + non-chat excluded, stale alias dropped
    assert aliases == ["coder-agentic", "coder-122b"]
    config = yaml.safe_load(hermes_config.read_text())
    models = config["custom_providers"][0]["models"]
    assert set(models) == {"coder-agentic", "coder-122b"}
    assert models["coder-agentic"]["context_length"] == 131072
    assert models["coder-122b"]["context_length"] == hermes_sync.DEFAULT_CONTEXT_LENGTH
    # untouched keys survive; a backup was written
    assert config["model"]["default"] == "coder-agentic"
    assert list(tmp_path.glob("config.yaml.presync.*.bak"))


def test_sync_missing_config_raises(manifest: Path, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        hermes_sync.sync_config(
            config_path=tmp_path / "nope.yaml", manifest_path=manifest
        )


def test_sync_no_matching_provider_raises(
    manifest: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"custom_providers": [{"name": "x", "base_url": "http://other:1"}]}))
    monkeypatch.setattr(hermes_sync, "fetch_model_ids", lambda base_url: ["a"])
    with pytest.raises(ValueError):
        hermes_sync.sync_config(config_path=p, manifest_path=manifest)


def test_sync_all_covers_every_profile(
    hermes_config: Path, manifest: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A profile is its own HERMES_HOME — syncing only the top-level config is
    the bug that left profiles/work/ without claude-opus-5 on 2026-07-26."""
    for name in ("work", "aipc"):
        profile = tmp_path / "profiles" / name
        profile.mkdir(parents=True)
        (profile / "config.yaml").write_text(hermes_config.read_text())
    monkeypatch.setattr(
        hermes_sync, "fetch_model_ids", lambda base_url: ["coder-agentic", "coder-122b"]
    )

    hermes_sync.sync_all(home=tmp_path, manifest_path=manifest)

    for path in hermes_sync.config_paths(tmp_path):
        models = yaml.safe_load(path.read_text())["custom_providers"][0]["models"]
        assert set(models) == {"coder-agentic", "coder-122b"}, path
    assert len(hermes_sync.config_paths(tmp_path)) == 3


def test_sync_mirrors_claude_aliases_into_cliproxy_providers(
    hermes_config: Path, manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = yaml.safe_load(hermes_config.read_text())
    config["custom_providers"].append(
        {
            "name": "cliproxy-claude",
            "base_url": "http://127.0.0.1:8317",
            "api_mode": "anthropic_messages",
            "models": {"claude-sonnet-5": {"context_length": 200000}},
        }
    )
    hermes_config.write_text(yaml.safe_dump(config, sort_keys=False))
    monkeypatch.setattr(
        hermes_sync,
        "fetch_model_ids",
        lambda base_url: ["coder-agentic", "claude-opus-5", "claude-sonnet-5"],
    )

    hermes_sync.sync_config(config_path=hermes_config, manifest_path=manifest)

    written = yaml.safe_load(hermes_config.read_text())["custom_providers"][1]["models"]
    assert set(written) == {"claude-sonnet-5", "claude-opus-5"}
    assert written["claude-opus-5"]["context_length"] == hermes_sync.CLIPROXY_CONTEXT_LENGTH


def test_sync_all_skips_profiles_without_the_gateway(
    hermes_config: Path, manifest: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = tmp_path / "profiles" / "other"
    other.mkdir(parents=True)
    (other / "config.yaml").write_text(
        yaml.safe_dump({"custom_providers": [{"name": "x", "base_url": "http://other:1"}]})
    )
    monkeypatch.setattr(hermes_sync, "fetch_model_ids", lambda base_url: ["coder-agentic"])

    assert hermes_sync.sync_all(home=tmp_path, manifest_path=manifest) == ["coder-agentic"]
