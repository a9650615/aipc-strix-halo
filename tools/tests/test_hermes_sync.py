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
                        "url": "http://127.0.0.1:4000",
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
    p.write_text(yaml.safe_dump({"custom_providers": [{"name": "x", "url": "http://other:1"}]}))
    monkeypatch.setattr(hermes_sync, "fetch_model_ids", lambda base_url: ["a"])
    with pytest.raises(ValueError):
        hermes_sync.sync_config(config_path=p, manifest_path=manifest)
