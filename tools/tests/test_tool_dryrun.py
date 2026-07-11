"""Dry-run agent tools + timeout alignment — real imports, bounded waits."""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "modules/agent-orchestrator/files/usr/lib/aipc-agent"
TOOLS_ROOTS = [
    ROOT / "modules/agent-tools-files/files/usr/lib/aipc-agent",
    ROOT / "modules/agent-tools-calendar/files/usr/lib/aipc-agent",
    ROOT / "modules/agent-tools-search/files/usr/lib/aipc-agent",
    ROOT / "modules/agent-tools-usage/files/usr/lib/aipc-agent",
    AGENT,
]
for p in TOOLS_ROOTS:
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Prefer short usage timeout in tests
os.environ.setdefault("AIPC_USAGE_TIMEOUT", "5")
os.environ.setdefault("AIPC_SEARCH_TIMEOUT", "3")


def test_timeout_matrix_voice_gt_hermes_voice():
    """Voice chat wait must exceed Hermes voice wall so timeout is explicit."""
    once = (ROOT / "modules/voice-pipecat/files/usr/bin/aipc-voice-once").read_text()
    hermes = (
        ROOT
        / "modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/hermes_bridge.py"
    ).read_text()
    # Defaults: voice chat outer > hermes voice wall (long-task matrix)
    assert 'AIPC_VOICE_CHAT_TIMEOUT", "780"' in once or 'CHAT_TIMEOUT", "780"' in once
    assert 'AIPC_HERMES_VOICE_TIMEOUT", "720"' in hermes
    assert 'AIPC_HERMES_LONG_TIMEOUT", "1800"' in hermes or "HERMES_LONG_TIMEOUT" in hermes
    # Long flow lives in task_jobs (any worker), not hermes_bridge.run_background
    jobs = (
        ROOT
        / "modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/task_jobs.py"
    ).read_text()
    assert "def submit(" in jobs
    # Structural: voice timeout string exists and is higher budget path
    assert "CHAT_TIMEOUT" in once
    assert "HERMES_VOICE_TIMEOUT" in hermes
    assert "处理超时" in once or "超时" in once
    # urllib.urlopen raises URLError(TimeoutError), not bare TimeoutError alone
    assert "_is_timeout_exc" in once
    assert "URLError" in once



def test_raw_tool_dryruns_return_status_quickly():
    from aipc_agent_tools_calendar.backends import lookup_events, lookup_email
    from aipc_agent_tools_search.search import search_searxng, search_tavily
    from aipc_agent_tools_usage.usage import lookup_usage

    t0 = time.monotonic()
    ev = lookup_events("today")
    assert time.monotonic() - t0 < 10
    assert ev.get("status") in ("ok", "not_configured", "error", "denied")

    t0 = time.monotonic()
    em = lookup_email("x")
    assert time.monotonic() - t0 < 10
    assert em.get("status") in ("ok", "not_configured", "error", "denied")

    t0 = time.monotonic()
    se = search_searxng("x")
    assert time.monotonic() - t0 < 10
    assert se.get("status") in ("ok", "not_configured", "error")

    t0 = time.monotonic()
    tv = search_tavily("x")
    assert time.monotonic() - t0 < 10
    assert tv.get("status") in ("ok", "not_configured", "error")

    t0 = time.monotonic()
    us = lookup_usage(None)
    assert time.monotonic() - t0 < 12
    assert us.get("status") in ("ok", "not_configured", "error")


def test_files_read_wrapper_denied_not_crash():
    # Load daily_assistant from source tree if deps present
    try:
        from aipc_agent.daily_assistant import files_read
    except Exception as exc:
        pytest.skip(f"daily_assistant import needs langgraph: {exc}")
    t0 = time.monotonic()
    r = files_read.invoke({"path": "/etc/hosts"})
    assert time.monotonic() - t0 < 5
    assert r.get("status") in ("ok", "denied", "not_configured", "error")


def test_route_negatives_and_humanize():
    try:
        from aipc_agent.graphs import _route, wants_hermes, wants_daily_assistant
        from aipc_agent import ux_bridge
    except Exception as exc:
        pytest.skip(f"graphs import: {exc}")
    assert _route({"text": "帮我写一首诗", "session_id": "s"}) == "respond"
    assert wants_hermes("shell 是什么") is False
    # EN substring traps (search⊂research, read⊂already is not word-bound issue)
    assert wants_daily_assistant("what is research") is False
    assert wants_daily_assistant("I already told you") is False
    assert wants_daily_assistant("my profile") is False
    assert _route({"text": "what is research", "session_id": "s"}) == "respond"
    assert wants_daily_assistant("web search for python") is True
    assert "工具" in ux_bridge.humanize_tools([])


def test_tool_node_path_with_mocked_llm():
    """AC4: ToolNode path with real tools + mocked LLM (no hang, structured tool result)."""
    try:
        from unittest.mock import patch

        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        from aipc_agent import daily_assistant as da
    except Exception as exc:
        pytest.skip(f"deps: {exc}")

    # AIMessage that requests usage_lookup then finishes after tool result
    call1 = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "usage_lookup",
                "args": {"providers": ""},
                "id": "call_usage_1",
            }
        ],
    )
    call2 = AIMessage(content="用量工具已回应。")

    inv = {"n": 0}

    def fake_invoke(self, *args, **kwargs):
        # ChatLiteLLM / RunnableBinding may pass (messages,) or (messages, config)
        inv["n"] += 1
        if inv["n"] == 1:
            return call1
        return call2

    from langchain_litellm import ChatLiteLLM

    # bind_tools() returns RunnableBinding that still delegates to ChatLiteLLM.invoke
    with patch.object(ChatLiteLLM, "invoke", fake_invoke):
        graph = da.daily_assistant()
        t0 = time.monotonic()
        result = graph.invoke(
            {"text": "查一下用量", "session_id": "s-tool-loop", "messages": []}
        )
        elapsed = time.monotonic() - t0
    assert elapsed < 20, f"tool loop too slow: {elapsed:.1f}s"
    assert result.get("text")
    # tool was invoked: second LLM turn after ToolNode
    assert inv["n"] >= 2, f"expected tool loop LLM turns, got n={inv['n']} text={result.get('text')!r}"
    assert "用量" in result["text"] or len(result["text"]) > 0
