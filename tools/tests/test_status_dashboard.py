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
