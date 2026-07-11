"""Secondary questions: coding agent pick across two turns (same session_id)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "modules/agent-orchestrator/files/usr/lib/aipc-agent"
sys.path.insert(0, str(AGENT))


def test_coding_triggers_clarify_then_resolves():
    os.environ["AIPC_CLARIFY"] = "1"
    os.environ["AIPC_CLASSIFIER"] = "0"  # keyword/rules only
    from aipc_agent import graphs, session_pending

    sid = "voice-clarify-1"
    session_pending.clear(sid)

    p1 = graphs.plan_dispatch("帮我写代码实现排序", sid)
    assert p1["target"] == "clarify"
    assert "Hermes" in (p1.get("clarify_question") or "")
    assert session_pending.get(sid) is not None

    # Wrong answer → re-ask
    p_bad = graphs.plan_dispatch("蓝色", sid)
    assert p_bad["target"] == "clarify"

    # Pick Hermes
    p2 = graphs.plan_dispatch("一", sid)
    assert p2["target"] == "hermes"
    assert p2["agent"] == "hermes"
    assert "排序" in (p2.get("original_text") or "")
    assert session_pending.get(sid) is None


def test_coding_pick_coder_agentic():
    os.environ["AIPC_CLARIFY"] = "1"
    os.environ["AIPC_CLASSIFIER"] = "0"
    from aipc_agent import graphs, session_pending

    sid = "voice-clarify-2"
    session_pending.clear(sid)
    assert graphs.plan_dispatch("帮我写代码", sid)["target"] == "clarify"
    p = graphs.plan_dispatch("二", sid)
    assert p["target"] == "coder"
    assert p["agent"] == "coder-agentic"


def test_explicit_hermes_skips_clarify():
    os.environ["AIPC_CLARIFY"] = "1"
    os.environ["AIPC_CLASSIFIER"] = "0"
    from aipc_agent import graphs, session_pending

    sid = "voice-clarify-3"
    session_pending.clear(sid)
    p = graphs.plan_dispatch("用hermes帮我写代码", sid)
    assert p["target"] == "hermes"
    assert p.get("agent") in ("hermes", "")


def test_cancel_pending():
    os.environ["AIPC_CLARIFY"] = "1"
    os.environ["AIPC_CLASSIFIER"] = "0"
    from aipc_agent import graphs, session_pending

    sid = "voice-clarify-4"
    session_pending.clear(sid)
    graphs.plan_dispatch("帮我写代码", sid)
    p = graphs.plan_dispatch("取消", sid)
    assert p["target"] == "respond"
    assert "取消" in (p.get("force_text") or "")
    assert session_pending.get(sid) is None


def test_parse_agent_choice():
    from aipc_agent.session_pending import parse_agent_choice

    assert parse_agent_choice("1") == "hermes"
    assert parse_agent_choice("用二") == "coder-agentic"
    assert parse_agent_choice("云端") == "coder-cloud"
    assert parse_agent_choice("hermes") == "hermes"
