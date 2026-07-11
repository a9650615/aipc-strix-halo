"""Compact isolation: NPU coder-compact lane must stay off Vulkan coder-agentic.

Shipped config + sync helpers are the real entry points clients re-run after
model list changes; these tests drive those paths (no reimplemented routing).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from aipc_lib import ccs_sync, opencode_sync

REPO = Path(__file__).resolve().parents[2]
LITELLM_CONFIG = REPO / "modules/llm-litellm/files/etc/aipc/litellm/config.yaml"
OPENCODE_SKEL = (
    REPO / "modules/dev-ai-opencode/files/etc/skel/.config/opencode/config.json"
)


def _litellm_entries() -> dict[str, dict]:
    raw = yaml.safe_load(LITELLM_CONFIG.read_text())
    out: dict[str, dict] = {}
    for entry in raw.get("model_list") or []:
        name = entry.get("model_name")
        if name:
            out[name] = entry
    return out


def test_shipped_litellm_has_npu_compact_alias_distinct_from_vulkan_coder() -> None:
    entries = _litellm_entries()
    assert "coder-compact" in entries
    assert "coder-agentic" in entries

    compact = entries["coder-compact"]["litellm_params"]
    agentic = entries["coder-agentic"]["litellm_params"]

    assert compact["model"] == "openai/gemma4-it-e4b-FLM"
    assert compact["api_base"] == "http://127.0.0.1:8001/v1"
    assert compact["num_retries"] == 0
    assert "Qwen" in agentic["model"] or "qwen" in agentic["model"].lower()
    assert agentic["model"] != compact["model"]
    assert agentic["num_retries"] == 0


def test_shipped_opencode_skel_routes_small_model_to_compact() -> None:
    skel = json.loads(OPENCODE_SKEL.read_text())
    assert skel["model"] == "aipc/coder-agentic"
    assert skel["small_model"] == "aipc/coder-compact"
    assert skel["compaction"]["prune"] is True
    assert skel["provider"]["aipc"]["models"]["coder-agentic"]["limit"]["context"] == 131072
    assert "coder-compact" in skel["provider"]["aipc"]["models"]


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


def test_ccs_sync_forces_haiku_to_coder_compact(tmp_path: Path) -> None:
    settings = tmp_path / "aipc.settings.json"
    settings.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_MODEL": "coder-agentic",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": "coder-agentic",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": "coder-agentic",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "coder-agentic",
                    "ANTHROPIC_EXTRA_MODELS": "stale",
                }
            }
        )
    )
    payload = {
        "data": [
            {"id": "coder-agentic"},
            {"id": "coder-compact"},
            {"id": "resident-small"},
            {"id": "ornith-35b"},
        ]
    }
    no_manifest = tmp_path / "missing.yaml"
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        ccs_sync.sync_extra_models(settings_path=settings, manifest_path=no_manifest)

    written = json.loads(settings.read_text())
    assert written["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "coder-compact"
    assert written["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "coder-agentic"
    assert written["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "coder-agentic"
    extras = written["env"]["ANTHROPIC_EXTRA_MODELS"].split(",")
    assert "coder-compact" in extras
    assert "coder-agentic" not in extras


def test_opencode_sync_sets_small_model_and_prune(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "model": "aipc/coder-agentic",
                "provider": {
                    "aipc": {
                        "npm": "@ai-sdk/openai-compatible",
                        "options": {"baseURL": "http://127.0.0.1:4000/v1"},
                        "models": {},
                    }
                },
            }
        )
    )
    payload = {
        "data": [
            {"id": "coder-agentic"},
            {"id": "coder-compact"},
            {"id": "resident-small"},
        ]
    }
    no_manifest = tmp_path / "missing.yaml"
    with patch("urllib.request.urlopen", _fake_urlopen(payload)):
        opencode_sync.sync_config(config_path=config_path, manifest_path=no_manifest)

    written = json.loads(config_path.read_text())
    assert written["model"] == "aipc/coder-agentic"
    assert written["small_model"] == "aipc/coder-compact"
    assert written["compaction"]["prune"] is True
    assert written["compaction"]["auto"] is True
    assert "coder-compact" in written["provider"]["aipc"]["models"]


def test_opencode_sync_caps_lemonade_context_to_recipe_ceiling(
    tmp_path: Path,
) -> None:
    """Lemonade card max (262k) must not override loaded 131k recipe."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "model": "aipc/coder-agentic",
                "provider": {
                    "aipc": {
                        "options": {"baseURL": "http://127.0.0.1:4000/v1"},
                        "models": {},
                    }
                },
            }
        )
    )
    manifest = tmp_path / "models.yaml"
    manifest.write_text(
        "models:\n"
        "  - alias: coder-agentic\n"
        "    backend: lemonade\n"
        "    model_id: Qwen3.6-35B-A3B-Uncensored-Aggressive-Q4_K_P\n"
        "    size_gb: 20\n"
    )

    def _opener(url: str, timeout: float = 5):
        if "4000" in url:
            return _FakeResponse({"data": [{"id": "coder-agentic"}]})
        if "8001" in url:
            return _FakeResponse(
                {
                    "data": [
                        {
                            "id": "Qwen3.6-35B-A3B-Uncensored-Aggressive-Q4_K_P",
                            "max_context_window": 262144,
                        }
                    ]
                }
            )
        raise AssertionError(url)

    with patch("urllib.request.urlopen", _opener):
        opencode_sync.sync_config(config_path=config_path, manifest_path=manifest)

    written = json.loads(config_path.read_text())
    assert written["provider"]["aipc"]["models"]["coder-agentic"]["limit"]["context"] == 131072
