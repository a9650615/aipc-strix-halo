from __future__ import annotations

import json
from pathlib import Path

import pytest

from aipc_lib import mem0_local_mcp


def _make_install(root: Path) -> mem0_local_mcp.Mem0Install:
    (root / "aipc_mem0").mkdir(parents=True)
    python = root / "venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    return mem0_local_mcp.Mem0Install(root=root, python=python)


def test_find_install_picks_first_valid_candidate(tmp_path):
    first = tmp_path / "etc-aipc-mem0"
    second = tmp_path / "usr-lib-aipc-mem0"
    _make_install(first)
    _make_install(second)

    install = mem0_local_mcp.find_install((first, second))

    assert install.root == first
    assert install.python == first / "venv/bin/python"


def test_find_install_fails_when_no_candidate_is_valid(tmp_path):
    with pytest.raises(mem0_local_mcp.Mem0LocalMcpError) as exc:
        mem0_local_mcp.find_install((tmp_path / "missing",))

    message = str(exc.value)
    assert "aipc-mem0 module/venv not found" in message
    assert "install/enable the memory-mem0 module first" in message
    assert "aipc doctor" in message


def test_point_claude_plugin_rewrites_to_local_stdio_mcp(tmp_path):
    install = mem0_local_mcp.Mem0Install(
        root=Path("/tmp/aipc-mem0"),
        python=Path("/tmp/aipc-mem0/venv/bin/python"),
    )
    plugin = tmp_path / ".claude/plugins/cache/mem0-plugins/mem0/0.2.12/.mcp.json"
    plugin.parent.mkdir(parents=True)
    plugin.write_text('{"old":"config"}\n')

    paths = mem0_local_mcp.point_claude_plugin(home=tmp_path, install=install)

    assert paths == [plugin]
    data = json.loads(plugin.read_text())
    mem0 = data["mcpServers"]["mem0"]
    assert mem0["type"] == "stdio"
    assert mem0["command"] == str(install.python)
    assert mem0["args"] == ["-m", "aipc_mem0.mcp_server"]
    assert mem0["env"] == {
        "PYTHONPATH": str(install.root),
        "MEM0_TELEMETRY": "False",
    }

    raw = plugin.read_text()
    assert "mcp.mem0.ai" not in raw
    assert "MEM0_API_KEY" not in raw
    assert "Authorization" not in raw
    assert "birdyo" not in raw


def test_point_claude_plugin_fails_when_plugin_cache_is_missing(tmp_path):
    install = _make_install(tmp_path / "aipc-mem0")

    with pytest.raises(mem0_local_mcp.Mem0LocalMcpError) as exc:
        mem0_local_mcp.point_claude_plugin(home=tmp_path, install=install)

    message = str(exc.value)
    assert "No mem0 plugin .mcp.json found" in message
    assert "install/enable the Claude Code mem0 plugin first" in message
