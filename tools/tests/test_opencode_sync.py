from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipc_lib import opencode_sync


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


def test_fetch_model_ids_parses_v1_models_response() -> None:
    payload = {"data": [{"id": "coder-fast"}, {"id": "coder-strong"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ids = opencode_sync.fetch_model_ids()
    assert ids == ["coder-fast", "coder-strong"]


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    p = tmp_path / "config.json"
    p.write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "model": "aipc/coder-agentic",
                "provider": {
                    "aipc": {
                        "npm": "@ai-sdk/openai-compatible",
                        "options": {"baseURL": "http://127.0.0.1:4000/v1"},
                        "models": {"coder-fast": {"name": "stale"}},
                    }
                },
            }
        )
    )
    return p


@pytest.fixture()
def no_manifest(tmp_path: Path) -> Path:
    # Deliberately nonexistent — isolates tests from whatever models.yaml
    # happens to exist on the host machine running the test suite.
    return tmp_path / "no-such-manifest.yaml"


def test_sync_config_replaces_models_dict(config_path: Path, no_manifest: Path) -> None:
    payload = {"data": [{"id": "coder-fast"}, {"id": "coder-agentic"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ids = opencode_sync.sync_config(config_path=config_path, manifest_path=no_manifest)

    assert ids == ["coder-fast", "coder-agentic"]
    written = json.loads(config_path.read_text())
    assert written["provider"]["aipc"]["models"] == {
        "coder-fast": {"name": "coder-fast"},
        "coder-agentic": {"name": "coder-agentic"},
    }


def test_sync_config_preserves_default_model_if_still_present(
    config_path: Path, no_manifest: Path
) -> None:
    payload = {"data": [{"id": "coder-fast"}, {"id": "coder-agentic"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path, manifest_path=no_manifest)

    written = json.loads(config_path.read_text())
    assert written["model"] == "aipc/coder-agentic"


def test_sync_config_falls_back_to_first_model_if_default_missing(
    config_path: Path, no_manifest: Path
) -> None:
    payload = {"data": [{"id": "coder-fast"}, {"id": "resident-small"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path, manifest_path=no_manifest)

    written = json.loads(config_path.read_text())
    assert written["model"] == "aipc/coder-fast"


def test_sync_config_raises_on_empty_model_list(config_path: Path, no_manifest: Path) -> None:
    payload = {"data": []}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        with pytest.raises(ValueError):
            opencode_sync.sync_config(config_path=config_path, manifest_path=no_manifest)


def test_sync_config_creates_config_if_missing(tmp_path: Path, no_manifest: Path) -> None:
    config_path = tmp_path / "nested" / "config.json"
    payload = {"data": [{"id": "coder-fast"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path, manifest_path=no_manifest)

    written = json.loads(config_path.read_text())
    assert written["provider"]["aipc"]["models"] == {"coder-fast": {"name": "coder-fast"}}


def test_sync_config_excludes_non_chat_aliases(config_path: Path, no_manifest: Path) -> None:
    payload = {"data": [{"id": "coder-fast"}, {"id": "embed-bge"}, {"id": "intent-3b"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ids = opencode_sync.sync_config(config_path=config_path, manifest_path=no_manifest)

    assert ids == ["coder-fast"]
    written = json.loads(config_path.read_text())
    assert "embed-bge" not in written["provider"]["aipc"]["models"]
    assert "intent-3b" not in written["provider"]["aipc"]["models"]


def test_sync_config_uses_manifest_model_id_and_size_for_display_name(
    config_path: Path, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        "models:\n"
        "  - alias: coder-fast\n"
        "    backend: ollama\n"
        "    model_id: qwen2.5-coder:7b-instruct-q4_K_M\n"
        "    size_gb: 4.5\n"
    )
    payload = {"data": [{"id": "coder-fast"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path, manifest_path=manifest_path)

    written = json.loads(config_path.read_text())
    assert written["provider"]["aipc"]["models"] == {
        "coder-fast": {"name": "coder-fast (qwen2.5-coder:7b-instruct-q4_K_M, 4.5GB)"}
    }


def test_sync_config_shows_cloud_instead_of_gb_for_cloud_aliases(
    config_path: Path, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        "models:\n"
        "  - alias: coder-cloud\n"
        "    backend: anthropic\n"
        "    model_id: claude-sonnet-4-6\n"
        "    size_gb: cloud\n"
    )
    payload = {"data": [{"id": "coder-cloud"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path, manifest_path=manifest_path)

    written = json.loads(config_path.read_text())
    assert written["provider"]["aipc"]["models"] == {
        "coder-cloud": {"name": "coder-cloud (claude-sonnet-4-6, cloud)"}
    }


def _fake_urlopen_by_url(responses: dict[str, dict]):
    def _opener(url: str, timeout: float = 5):
        for needle, payload in responses.items():
            if needle in url:
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected URL in test: {url}")

    return _opener


def test_sync_config_adds_limit_for_lemonade_backed_alias(
    config_path: Path, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        "models:\n"
        "  - alias: ornith-35b\n"
        "    backend: lemonade\n"
        "    model_id: Ornith-1.0-35B-GGUF-Q4_K_M\n"
        "    size_gb: 19.7\n"
    )
    responses = {
        "127.0.0.1:4000": {"data": [{"id": "ornith-35b"}]},
        "127.0.0.1:8001": {
            "data": [{"id": "Ornith-1.0-35B-GGUF-Q4_K_M", "max_context_window": 262144}]
        },
    }
    with patch("urllib.request.urlopen", _fake_urlopen_by_url(responses)):
        opencode_sync.sync_config(config_path=config_path, manifest_path=manifest_path)

    written = json.loads(config_path.read_text())
    # Lemonade may advertise card max 262144; sync caps to loaded recipe ceiling.
    assert written["provider"]["aipc"]["models"]["ornith-35b"]["limit"] == {
        "context": 131072,
        "output": 16384,
    }


def test_sync_config_omits_limit_for_non_lemonade_alias(config_path: Path, tmp_path: Path) -> None:
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        "models:\n"
        "  - alias: coder-cloud\n"
        "    backend: anthropic\n"
        "    model_id: claude-sonnet-4-6\n"
        "    size_gb: cloud\n"
    )
    payload = {"data": [{"id": "coder-cloud"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path, manifest_path=manifest_path)

    written = json.loads(config_path.read_text())
    assert "limit" not in written["provider"]["aipc"]["models"]["coder-cloud"]


def test_sync_config_omits_limit_when_lemonade_unreachable(
    config_path: Path, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        "models:\n"
        "  - alias: ornith-35b\n"
        "    backend: lemonade\n"
        "    model_id: Ornith-1.0-35B-GGUF-Q4_K_M\n"
        "    size_gb: 19.7\n"
    )

    def _opener(url: str, timeout: float = 5):
        if "127.0.0.1:4000" in url:
            return _FakeResponse({"data": [{"id": "ornith-35b"}]})
        raise OSError("connection refused")

    with patch("urllib.request.urlopen", _opener):
        opencode_sync.sync_config(config_path=config_path, manifest_path=manifest_path)

    written = json.loads(config_path.read_text())
    assert "limit" not in written["provider"]["aipc"]["models"]["ornith-35b"]
