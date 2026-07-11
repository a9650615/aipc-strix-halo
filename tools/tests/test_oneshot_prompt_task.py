"""One-shot: agent + prompt + task in a single utterance (no secondary ask)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "modules/agent-orchestrator/files/usr/lib/aipc-agent"
sys.path.insert(0, str(AGENT))


def test_parse_prompt_and_task():
    from aipc_agent.session_pending import parse_prompt_and_task, parse_oneshot

    pt = parse_prompt_and_task("提示词：你是严谨工程师。任务：重构 auth 模块")
    assert pt is not None
    assert "严谨" in pt["system"]
    assert "auth" in pt["task"]

    one = parse_oneshot("提示词：简洁。任务：实现快速排序")
    assert one is not None
    assert one["agent"] == "hermes"
    assert "System" in one["original_text"] or "简洁" in one["original_text"]
    assert "快速排序" in one["original_text"]


def test_oneshot_agent_plus_task_no_clarify():
    os.environ["AIPC_CLARIFY"] = "auto"
    os.environ["AIPC_CLASSIFIER"] = "0"
    from aipc_agent import graphs, session_pending

    sid = "voice-oneshot-1"
    session_pending.clear(sid)
    p = graphs.plan_dispatch("用 Hermes 帮我写一个快速排序函数", sid)
    assert p["target"] == "hermes"
    assert p["agent"] == "hermes"
    assert p["source"] == "oneshot"
    assert "快速排序" in p["original_text"]
    assert session_pending.get(sid) is None  # no pending ask


def test_oneshot_full_task_defaults_hermes():
    os.environ["AIPC_CLARIFY"] = "auto"
    os.environ["AIPC_CLASSIFIER"] = "0"
    from aipc_agent import graphs, session_pending

    sid = "voice-oneshot-2"
    session_pending.clear(sid)
    p = graphs.plan_dispatch("帮我写代码实现链表反转并写测试", sid)
    assert p["target"] == "hermes"
    assert p.get("source") == "oneshot"
    assert session_pending.get(sid) is None


def test_bare_coding_still_clarifies_in_auto():
    os.environ["AIPC_CLARIFY"] = "auto"
    os.environ["AIPC_CLASSIFIER"] = "0"
    from aipc_agent import graphs, session_pending

    sid = "voice-oneshot-3"
    session_pending.clear(sid)
    p = graphs.plan_dispatch("帮我写代码", sid)
    assert p["target"] == "clarify"


def test_prompt_task_with_local_coder():
    os.environ["AIPC_CLARIFY"] = "auto"
    from aipc_agent.session_pending import parse_oneshot, plan_from_oneshot

    one = parse_oneshot(
        "用本地编码 提示词：输出 Python3。任务：写斐波那契"
    )
    # agent named + prompt/task
    assert one is not None
    # If both patterns present, prompt+task path may win with hermes default
    # unless agent is detected — either is ok if task preserved
    plan = plan_from_oneshot(one)
    assert plan["target"] in ("hermes", "coder")
    assert "斐波那契" in plan["original_text"] or "斐波那契" in (one.get("original_text") or "")
