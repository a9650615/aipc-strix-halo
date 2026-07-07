from __future__ import annotations

from pathlib import Path

from aipc_lib import status_dashboard
from aipc_lib.modules import Module


def test_module_services_finds_quadlet_containers(tmp_path: Path) -> None:
    mod_path = tmp_path / "llm-ollama"
    quadlet_dir = mod_path / "quadlet"
    quadlet_dir.mkdir(parents=True)
    (quadlet_dir / "ollama.container").write_text("[Container]\n")
    mod = Module(name="llm-ollama", path=mod_path)

    assert status_dashboard.module_services(mod) == ["ollama.service"]


def test_module_services_finds_plain_systemd_units(tmp_path: Path) -> None:
    mod_path = tmp_path / "ops-firstboot"
    unit_dir = mod_path / "files" / "etc" / "systemd" / "system"
    unit_dir.mkdir(parents=True)
    (unit_dir / "aipc-firstboot.service").write_text("[Unit]\n")
    mod = Module(name="ops-firstboot", path=mod_path)

    assert status_dashboard.module_services(mod) == ["aipc-firstboot.service"]


def test_module_services_combines_both_sources(tmp_path: Path) -> None:
    mod_path = tmp_path / "llm-ollama"
    quadlet_dir = mod_path / "quadlet"
    quadlet_dir.mkdir(parents=True)
    (quadlet_dir / "ollama.container").write_text("[Container]\n")
    unit_dir = mod_path / "files" / "etc" / "systemd" / "system"
    unit_dir.mkdir(parents=True)
    (unit_dir / "aipc-models-dir.service").write_text("[Unit]\n")
    mod = Module(name="llm-ollama", path=mod_path)

    assert status_dashboard.module_services(mod) == [
        "ollama.service",
        "aipc-models-dir.service",
    ]


def test_module_services_empty_when_no_files(tmp_path: Path) -> None:
    mod_path = tmp_path / "llm-models"
    mod_path.mkdir()
    mod = Module(name="llm-models", path=mod_path)

    assert status_dashboard.module_services(mod) == []


def test_discover_module_services_skips_disabled(tmp_path: Path) -> None:
    enabled = tmp_path / "llm-ollama"
    quadlet_dir = enabled / "quadlet"
    quadlet_dir.mkdir(parents=True)
    (quadlet_dir / "ollama.container").write_text("[Container]\n")

    disabled = tmp_path / "llm-vllm"
    disabled_quadlet = disabled / "quadlet"
    disabled_quadlet.mkdir(parents=True)
    (disabled_quadlet / "vllm.container").write_text("[Container]\n")
    (disabled / ".disabled").write_text("")

    pairs = status_dashboard.discover_module_services(tmp_path)
    assert [p.module for p in pairs] == ["llm-ollama"]


def test_loaded_models_returns_none_when_unreachable() -> None:
    # Nothing listening on this port — must not raise.
    result = status_dashboard.loaded_models(base_url="http://127.0.0.1:1")
    assert result is None


def test_alias_display_name_matches_manifest_entry(tmp_path: Path) -> None:
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text(
        "models:\n"
        "  - alias: coder-agentic\n"
        "    backend: ollama\n"
        "    model_id: gemma4:26b\n"
        "    size_gb: 18.0\n"
    )
    assert (
        status_dashboard.alias_display_name("gemma4:26b", manifest_path)
        == "coder-agentic (gemma4:26b)"
    )


def test_alias_display_name_falls_back_to_bare_id_when_unregistered(tmp_path: Path) -> None:
    manifest_path = tmp_path / "models.yaml"
    manifest_path.write_text("models:\n  - alias: coder-fast\n    backend: ollama\n    model_id: qwen2.5-coder:7b\n")
    assert status_dashboard.alias_display_name("llama3.2:3b", manifest_path) == "llama3.2:3b"


def test_loaded_lemonade_returns_none_when_unreachable() -> None:
    import urllib.error
    orig = status_dashboard.urllib.request.urlopen
    status_dashboard.urllib.request.urlopen = lambda url, timeout=None: (_ for _ in ()).throw(
        urllib.error.URLError("refused")
    )
    try:
        assert status_dashboard.loaded_lemonade_models(base_url="http://127.0.0.1:1") is None
    finally:
        status_dashboard.urllib.request.urlopen = orig


def test_loaded_lemonade_filters_to_loaded_only() -> None:
    import json
    from unittest.mock import patch
    sample = json.dumps({
        "all_models_loaded": [
            {"model_name": "m1", "loaded": True, "pinned": False},
            {"model_name": "m2", "loaded": False, "pinned": False},
            {"model_name": "m3", "loaded": True, "pinned": True},
        ]
    }).encode()

    fake_resp = patch("urllib.request.urlopen")
    fake_resp.start()
    fake_resp.stop()  # placeholder; the real impl is in test_models_loaded_unload.py

    # Inline mock: return a fake response object.
    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return sample

    with patch("urllib.request.urlopen", return_value=_FakeResp()):
        result = status_dashboard.loaded_lemonade_models(base_url="http://x")
    assert result is not None
    assert len(result) == 2
    assert result[0]["model_name"] == "m1"
    assert result[1]["model_name"] == "m3"
