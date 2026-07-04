from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipc_lib import ccs_sync


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def _fake_urlopen(payload: dict):
    def _opener(url: str, timeout: float = 5):
        return _FakeResponse(payload)

    return _opener


@pytest.fixture()
def settings_path(tmp_path: Path) -> Path:
    p = tmp_path / "aipc.settings.json"
    p.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000",
                    "ANTHROPIC_AUTH_TOKEN": "aipc-local",
                    "ANTHROPIC_MODEL": "coder-agentic",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "coder-agentic",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": "coder-agentic",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "coder-agentic",
                    "ANTHROPIC_EXTRA_MODELS": "stale-model",
                    "CCS_DROID_PROVIDER": "anthropic",
                },
                "permissions": {"defaultMode": "bypassPermissions"},
            }
        )
    )
    return p


@pytest.fixture()
def no_manifest(tmp_path: Path) -> Path:
    # Deliberately nonexistent — isolates tests from whatever models.yaml
    # happens to exist on the host machine running the test suite.
    return tmp_path / "no-such-manifest.yaml"


def test_sync_extra_models_replaces_stale_list(settings_path: Path, no_manifest: Path) -> None:
    payload = {"data": [{"id": "coder-agentic"}, {"id": "ornith-35b"}, {"id": "resident-small"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ids = ccs_sync.sync_extra_models(settings_path=settings_path, manifest_path=no_manifest)

    assert ids == ["ornith-35b", "resident-small"]
    written = json.loads(settings_path.read_text())
    assert written["env"]["ANTHROPIC_EXTRA_MODELS"] == "ornith-35b,resident-small"


def test_sync_extra_models_excludes_current_default(settings_path: Path, no_manifest: Path) -> None:
    payload = {"data": [{"id": "coder-agentic"}, {"id": "ornith-35b"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ids = ccs_sync.sync_extra_models(settings_path=settings_path, manifest_path=no_manifest)

    assert "coder-agentic" not in ids
    assert ids == ["ornith-35b"]


def test_sync_extra_models_excludes_cloud_aliases(settings_path: Path, tmp_path: Path) -> None:
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        "models:\n"
        "  - alias: ornith-35b\n"
        "    backend: ollama\n"
        "    model_id: hf.co/deepreinforce-ai/Ornith-1.0-35B-GGUF:Q4_K_M\n"
        "    size_gb: 19.7\n"
        "  - alias: main-cloud\n"
        "    backend: anthropic\n"
        "    model_id: claude-sonnet-4-6\n"
        "    size_gb: cloud\n"
    )
    payload = {"data": [{"id": "coder-agentic"}, {"id": "ornith-35b"}, {"id": "main-cloud"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ids = ccs_sync.sync_extra_models(settings_path=settings_path, manifest_path=manifest_path)

    assert ids == ["ornith-35b"]
    assert "main-cloud" not in ids


def test_sync_extra_models_excludes_non_chat_aliases(settings_path: Path, no_manifest: Path) -> None:
    payload = {
        "data": [
            {"id": "coder-agentic"},
            {"id": "ornith-35b"},
            {"id": "embed-bge"},
            {"id": "intent-3b"},
        ]
    }
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ids = ccs_sync.sync_extra_models(settings_path=settings_path, manifest_path=no_manifest)

    assert ids == ["ornith-35b"]
    assert "embed-bge" not in ids
    assert "intent-3b" not in ids


def test_sync_extra_models_raises_if_nothing_left(settings_path: Path, no_manifest: Path) -> None:
    payload = {"data": [{"id": "coder-agentic"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        with pytest.raises(ValueError):
            ccs_sync.sync_extra_models(settings_path=settings_path, manifest_path=no_manifest)


def test_sync_extra_models_raises_if_settings_missing(tmp_path: Path, no_manifest: Path) -> None:
    missing = tmp_path / "aipc.settings.json"
    with pytest.raises(FileNotFoundError):
        ccs_sync.sync_extra_models(settings_path=missing, manifest_path=no_manifest)


def test_sync_extra_models_does_not_touch_default_model_keys(
    settings_path: Path, no_manifest: Path
) -> None:
    payload = {"data": [{"id": "coder-agentic"}, {"id": "ornith-35b"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ccs_sync.sync_extra_models(settings_path=settings_path, manifest_path=no_manifest)

    written = json.loads(settings_path.read_text())
    assert written["env"]["ANTHROPIC_MODEL"] == "coder-agentic"
    assert written["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "coder-agentic"
