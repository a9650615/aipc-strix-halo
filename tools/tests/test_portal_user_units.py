"""User-scope systemd units for CLIProxy / CodexBar portal cards."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PORTAL_LIB = Path(__file__).parents[2] / "modules/system-aipc-portal/files/usr/lib/aipc-portal"
sys.path.insert(0, str(PORTAL_LIB))

from aipc_portal.ops import service_group  # noqa: E402
from aipc_portal.registry import (  # noqa: E402
    ServiceMetadata,
    load_service_metadata,
    primary_user,
    start_unit,
    unit_command,
    unit_is_active,
)


def test_primary_user_prefers_aipc_primary() -> None:
    assert primary_user({"AIPC_PRIMARY_USER": "birdyo", "AIPC_HERMES_USER": "other"}) == "birdyo"
    assert primary_user({"AIPC_HERMES_USER": "alice"}) == "alice"
    assert primary_user({}) == ""


def test_unit_command_system_vs_user() -> None:
    assert unit_command("is-active", "litellm.service") == [
        "systemctl",
        "is-active",
        "litellm.service",
    ]
    cmd = unit_command(
        "is-active", "ccs-cliproxy.service", scope="user", user="birdyo"
    )
    assert cmd[:5] == ["runuser", "-u", "birdyo", "--", "env"]
    assert cmd[-4:] == ["systemctl", "--user", "is-active", "ccs-cliproxy.service"]
    assert any(x.startswith("XDG_RUNTIME_DIR=") for x in cmd)


def test_unit_is_active_user_scope_argv(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):  # noqa: ANN001
        seen.append(list(argv))

        class P:
            returncode = 0
            stdout = "active\n"
            stderr = ""

        return P()

    monkeypatch.setenv("AIPC_PRIMARY_USER", "birdyo")
    state = unit_is_active("ccs-cliproxy.service", runner=fake_run, scope="user")
    assert state == "active"
    assert seen[0][:5] == ["runuser", "-u", "birdyo", "--", "env"]
    assert "systemctl" in seen[0]
    assert "--user" in seen[0]


def test_start_unit_user_requires_primary(monkeypatch) -> None:
    monkeypatch.delenv("AIPC_PRIMARY_USER", raising=False)
    monkeypatch.delenv("AIPC_HERMES_USER", raising=False)
    ok, detail = start_unit("ccs-cliproxy.service", scope="user", runner=lambda *a, **k: None)
    assert not ok
    assert "AIPC_PRIMARY_USER" in detail


def test_start_unit_user_scope_argv(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):  # noqa: ANN001
        seen.append(list(argv))

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    monkeypatch.setenv("AIPC_PRIMARY_USER", "birdyo")
    ok, detail = start_unit("ccs-cliproxy.service", runner=fake_run, scope="user")
    assert ok and detail == "started"
    assert seen[0][:5] == ["runuser", "-u", "birdyo", "--", "env"]
    assert seen[0][-4:] == ["systemctl", "--user", "start", "ccs-cliproxy.service"]


def test_yaml_parses_systemd_scope_user(tmp_path: Path) -> None:
    services = tmp_path / "services"
    services.mkdir()
    (services / "cliproxy.yaml").write_text(
        """
id: cliproxy
title: CLIProxy (CCS)
module: ccs
kind: llm
systemd: ccs-cliproxy.service
systemd_scope: user
health: http://127.0.0.1:8317/
endpoint: http://127.0.0.1:8317
tags:
  - llm
  - oauth
""".strip()
        + "\n",
        encoding="utf-8",
    )
    loaded = load_service_metadata(services)
    assert len(loaded) == 1
    assert loaded[0].systemd_scope == "user"
    assert loaded[0].systemd == "ccs-cliproxy.service"


def test_service_group_collab_bridges() -> None:
    assert service_group("cliproxy") == "LLM"
    assert service_group("codexbar") == "Agent"
    assert service_group("litellm") == "LLM"


def test_module_cards_exist() -> None:
    root = Path(__file__).parents[2]
    clip = root / "modules/ccs/files/etc/aipc/portal/services/cliproxy.yaml"
    bar = root / "modules/dev-ai-codexbar-usage/files/etc/aipc/portal/services/codexbar.yaml"
    unit = root / "modules/ccs/files/usr/lib/systemd/user/ccs-cliproxy.service"
    assert clip.is_file() and "systemd_scope: user" in clip.read_text()
    assert bar.is_file() and "aipc-usage.service" in bar.read_text()
    assert unit.is_file() and "cli-proxy-api" in unit.read_text()
