"""Agent UX progress helpers (tool / Hermes feedback)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/ux_bridge.py"


def _load():
    spec = importlib.util.spec_from_file_location("ux_bridge_under_test", PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_humanize_tools():
    ux = _load()
    assert "日曆" in ux.humanize_tools(["calendar_lookup"])
    assert "工具" in ux.humanize_tools([])
    assert "files_read" in ux.humanize_tools(["files_read"]) or "讀" in ux.humanize_tools(
        ["files_read"]
    )


def test_tool_names_from_message():
    ux = _load()
    msg = SimpleNamespace(
        tool_calls=[{"name": "web_search", "args": {}}],
        additional_kwargs={},
    )
    assert ux.tool_names_from_message(msg) == ["web_search"]
    msg2 = SimpleNamespace(
        tool_calls=[],
        additional_kwargs={
            "tool_calls": [{"function": {"name": "calendar_lookup"}, "id": "1"}]
        },
    )
    assert "calendar_lookup" in ux.tool_names_from_message(msg2)


def test_working_state_in_voice_ux():
    from aipc_lib import voice_ux

    assert "working" in voice_ux.KNOWN_STATES
