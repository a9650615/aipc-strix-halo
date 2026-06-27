from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aipc_lib.modules import Module
from aipc_lib.render_ansible import render


@pytest.fixture()
def two_mods(tmp_path: Path) -> list[Module]:
    a = tmp_path / "mod-a"
    a.mkdir()
    b = tmp_path / "mod-b"
    b.mkdir()
    return [
        Module(name="mod-a", path=a, packages=["pkg-a1", "pkg-a2"], kargs=["karg=1"]),
        Module(name="mod-b", path=b, packages=["pkg-b1"], kargs=[]),
    ]


def test_valid_yaml(two_mods: list[Module]) -> None:
    out = render(two_mods)
    parsed = yaml.safe_load(out)
    assert isinstance(parsed, list)


def test_one_play_hosts_aipc(two_mods: list[Module]) -> None:
    parsed = yaml.safe_load(render(two_mods))
    assert len(parsed) == 1
    assert parsed[0]["hosts"] == "aipc"
    assert parsed[0]["become"] is True


def test_dnf_task_has_all_packages(two_mods: list[Module]) -> None:
    parsed = yaml.safe_load(render(two_mods))
    tasks = parsed[0]["tasks"]
    dnf_tasks = [t for t in tasks if "dnf" in t or "ansible.builtin.dnf" in t]
    assert len(dnf_tasks) == 1
    task = dnf_tasks[0]
    pkg_list = (task.get("dnf") or task.get("ansible.builtin.dnf"))["name"]
    assert "pkg-a1" in pkg_list
    assert "pkg-a2" in pkg_list
    assert "pkg-b1" in pkg_list


def test_kargs_command_task(two_mods: list[Module]) -> None:
    parsed = yaml.safe_load(render(two_mods))
    tasks = parsed[0]["tasks"]
    cmd_tasks = [t for t in tasks if "command" in t or "ansible.builtin.command" in t]
    assert any("karg=1" in str(t) for t in cmd_tasks)


def test_post_install_script_task(tmp_path: Path) -> None:
    m = tmp_path / "mod-x"
    m.mkdir()
    post = m / "post-install.sh"
    post.write_text("#!/bin/sh\necho hi\n")
    mods = [Module(name="mod-x", path=m, packages=[], kargs=[])]
    parsed = yaml.safe_load(render(mods))
    tasks = parsed[0]["tasks"]
    script_tasks = [t for t in tasks if "script" in t or "ansible.builtin.script" in t]
    assert any("mod-x" in str(t) for t in script_tasks)
