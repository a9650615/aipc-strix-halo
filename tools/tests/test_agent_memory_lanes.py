"""Agent-scoped mem0 lanes + short-term context isolation."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "modules/agent-orchestrator/files/usr/lib/aipc-agent"
sys.path.insert(0, str(AGENT))


def test_agent_lane_mapping():
    from aipc_agent import memory as m

    assert m.agent_lane("daily_assistant") == m.AGENT_DAILY
    assert m.agent_lane("coder-agentic") == m.AGENT_CODER
    assert m.agent_lane("hermes") == m.AGENT_HERMES
    assert m.agent_lane("coder-agentic") != m.agent_lane("daily")
    assert m.agent_lane("chat") != m.agent_lane("hermes")


def test_recall_passes_agent_id():
    from aipc_agent import memory as m

    seen = []

    def fake_post(path, payload, *, timeout=None):
        seen.append(payload)
        return {"results": []}

    with patch.object(m, "_post", side_effect=fake_post):
        m.recall("quota", "voice-1", agent=m.AGENT_DAILY)
        m.recall("sort code", "voice-1", agent=m.AGENT_CODER)
    daily_ids = {p["agent_id"] for p in seen if p.get("query") == "quota"}
    coder_ids = {p["agent_id"] for p in seen if p.get("query") == "sort code"}
    assert daily_ids == {m.AGENT_DAILY}
    assert coder_ids == {m.AGENT_CODER}


def test_agent_context_isolated_by_lane():
    from aipc_agent import agent_context

    sid = "sess-ctx-1"
    agent_context.clear(sid)
    agent_context.append_turn(sid, "daily", "user", "查用量")
    agent_context.append_turn(sid, "daily", "assistant", "已用1%")
    agent_context.append_turn(sid, "coder", "user", "写排序")
    agent_context.append_turn(sid, "coder", "assistant", "def sort...")
    daily = agent_context.format_history(sid, "daily")
    coder = agent_context.format_history(sid, "coder")
    assert "查用量" in daily
    assert "写排序" not in daily
    assert "写排序" in coder
    assert "查用量" not in coder


def test_try_direct_tool_off_by_default():
    import os

    from aipc_agent.daily_assistant import try_direct_tool

    os.environ.pop("AIPC_DAILY_DIRECT_TOOLS", None)
    assert try_direct_tool("查一下用量") is None
