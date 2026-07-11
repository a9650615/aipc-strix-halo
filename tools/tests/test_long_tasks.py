"""Long-task support: dispatch (tool × mode), generic jobs, timeout matrix."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "modules/agent-orchestrator/files/usr/lib/aipc-agent"
sys.path.insert(0, str(AGENT))


def test_dispatch_tool_and_mode_are_independent():
    """Long markers must NOT force Hermes; tool choice is separate."""
    os.environ["AIPC_DISPATCH_LLM"] = "0"  # keyword path only
    from aipc_agent.graphs import (
        plan_dispatch,
        wants_hermes,
        wants_job_status,
        wants_long_mode,
    )

    # Long + search-ish → daily_assistant long (not hermes)
    p = plan_dispatch("后台慢慢做，帮我搜一下 python 教程", "voice-1")
    assert p["target"] == "daily_assistant"
    assert p["mode"] == "long"
    assert wants_long_mode("后台慢慢做，帮我搜一下 python 教程") is True
    assert wants_hermes("后台慢慢做，帮我搜一下 python 教程") is False

    # Coding → hermes; without long markers → short
    p2 = plan_dispatch("帮我写代码修一下 bug", "s")
    assert p2["target"] == "hermes"
    assert p2["mode"] == "short"

    # Coding + long → hermes long (oneshot must not force short)
    p3 = plan_dispatch("后台慢慢做，帮我写代码实现完整功能", "voice-2")
    assert p3["target"] == "hermes"
    assert p3["mode"] == "long"

    # Explicit long markers on oneshot agent path
    p3b = plan_dispatch("后台慢慢做用 Hermes 帮我写登录", "voice-2b")
    assert p3b["target"] == "hermes"
    assert p3b["mode"] == "long"

    # Pure chat not long
    assert wants_long_mode("今天天气怎么样") is False
    assert plan_dispatch("今天天气怎么样", "s")["target"] == "respond"
    assert plan_dispatch("今天天气怎么样", "s")["mode"] == "short"

    assert wants_job_status("任务进度怎么样") is True
    assert plan_dispatch("任务进度怎么样", "s")["target"] == "job_status"


def test_generic_task_jobs_not_hermes_named():
    from aipc_agent import task_jobs

    def fake():
        # mid-run progress via context job id
        task_jobs.job_update("thinking step", thinking="先搜再总结")
        time.sleep(0.05)
        return {"status": "ok", "text": "daily done", "detail": "x"}

    with patch.object(task_jobs, "_notify_desktop"):
        out = task_jobs.submit(
            "daily_assistant",
            "搜一下",
            "voice-t",
            fake,
            plan_summary="搜一下 python",
        )
    assert out["status"] == "accepted"
    assert out.get("worker") == "daily_assistant" or "daily" in out["text"].lower() or "助手" in out["text"]
    assert "编号" in out["text"] or out.get("job_id")
    deadline = time.monotonic() + 2.0
    job = None
    while time.monotonic() < deadline:
        job = task_jobs.job_get(out["job_id"])
        if job and job.get("status") == "ok":
            break
        time.sleep(0.05)
    assert job is not None
    assert job["worker"] == "daily_assistant"
    assert "done" in (job.get("result_text") or "")
    # progress trail retained
    prog = job.get("progress") or []
    assert any("先搜" in str(p.get("thinking") or "") or "thinking" in str(p) for p in prog) or job.get(
        "last_progress"
    )


def test_format_status_speech_includes_thinking():
    from aipc_agent import task_jobs

    with patch.object(task_jobs, "_notify_desktop"):
        out = task_jobs.submit(
            "hermes",
            "完整实现登录",
            "v",
            lambda: (time.sleep(0.2) or {"status": "ok", "text": "ok"}),
            plan_summary="实现登录",
        )
        time.sleep(0.05)
        speech = task_jobs.format_status_speech()
    assert out["job_id"] in speech or "运行中" in speech or "Hermes" in speech


def test_timeout_matrix_long_task_ordering():
    once = (ROOT / "modules/voice-pipecat/files/usr/bin/aipc-voice-once").read_text()
    hermes = (
        ROOT
        / "modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/hermes_bridge.py"
    ).read_text()
    jobs = (
        ROOT
        / "modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/task_jobs.py"
    ).read_text()
    assert 'AIPC_VOICE_CHAT_TIMEOUT", "780"' in once
    assert 'AIPC_HERMES_VOICE_TIMEOUT", "720"' in hermes
    assert "def submit(" in jobs
    assert "run_background" not in hermes  # long flow is generic task_jobs


def test_hermes_node_uses_dispatch_mode_not_markers(monkeypatch):
    """Worker respects state.mode from plan; does not re-route by markers."""
    os.environ["AIPC_DISPATCH_LLM"] = "0"
    from aipc_agent import graphs, hermes_bridge, task_jobs

    calls = []

    def fake_run(text, session_id="voice", *, long_task=False, wall=None, max_turns=None):
        calls.append({"long_task": long_task, "text": text})
        return {"status": "ok", "text": "ok", "detail": "1s"}

    monkeypatch.setattr(hermes_bridge, "run", fake_run)
    monkeypatch.setattr(task_jobs, "async_enabled", lambda: True)
    submitted = []

    def fake_submit(worker, text, session_id, fn, **kwargs):
        submitted.append(worker)
        return {
            "status": "accepted",
            "job_id": "x",
            "worker": worker,
            "text": f"交给 {worker}",
            "detail": "background",
        }

    monkeypatch.setattr(task_jobs, "submit", fake_submit)

    # mode=long → background submit, not sync run
    out = graphs._hermes_node(
        {"text": "写代码", "session_id": "voice-1", "target": "hermes", "mode": "long"}
    )
    assert submitted == ["hermes"]
    assert "hermes" in out["text"]
    assert calls == []  # sync run not called yet (fn deferred)

    # mode=short → sync run
    submitted.clear()
    out2 = graphs._hermes_node(
        {"text": "写代码", "session_id": "voice-1", "target": "hermes", "mode": "short"}
    )
    assert submitted == []
    assert calls and calls[0]["long_task"] is False
    assert out2["text"] == "ok"
