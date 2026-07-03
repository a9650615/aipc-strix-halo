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


def test_sync_config_replaces_models_dict(config_path: Path) -> None:
    payload = {"data": [{"id": "coder-fast"}, {"id": "coder-agentic"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ids = opencode_sync.sync_config(config_path=config_path)

    assert ids == ["coder-fast", "coder-agentic"]
    written = json.loads(config_path.read_text())
    assert written["provider"]["aipc"]["models"] == {
        "coder-fast": {"name": "coder-fast"},
        "coder-agentic": {"name": "coder-agentic"},
    }


def test_sync_config_preserves_default_model_if_still_present(config_path: Path) -> None:
    payload = {"data": [{"id": "coder-fast"}, {"id": "coder-agentic"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path)

    written = json.loads(config_path.read_text())
    assert written["model"] == "aipc/coder-agentic"


def test_sync_config_falls_back_to_first_model_if_default_missing(config_path: Path) -> None:
    payload = {"data": [{"id": "coder-fast"}, {"id": "resident-small"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path)

    written = json.loads(config_path.read_text())
    assert written["model"] == "aipc/coder-fast"


def test_sync_config_raises_on_empty_model_list(config_path: Path) -> None:
    payload = {"data": []}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        with pytest.raises(ValueError):
            opencode_sync.sync_config(config_path=config_path)


def test_sync_config_creates_config_if_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "config.json"
    payload = {"data": [{"id": "coder-fast"}]}
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path)

    written = json.loads(config_path.read_text())
    assert written["provider"]["aipc"]["models"] == {"coder-fast": {"name": "coder-fast"}}
