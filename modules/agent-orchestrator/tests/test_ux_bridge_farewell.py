"""finish_answer() farewell detection: a closing remark skips the followup
invite instead of showing "可接話" for a fixed ttl after a long done hold."""

from __future__ import annotations

import sys
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
AGENT_LIB = MODULE / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(AGENT_LIB))


def test_looks_like_farewell_matches_closing_remarks():
    from aipc_agent import ux_bridge

    assert ux_bridge._looks_like_farewell(
        "好的，那我就先休息了。如果您需要我，随时可以叫我。"
    )
    assert ux_bridge._looks_like_farewell("晚安，明天再聊")
    assert not ux_bridge._looks_like_farewell("今天台北天氣是晴天，氣溫28度")


def test_finish_answer_farewell_skips_followup_thread(monkeypatch):
    from aipc_agent import ux_bridge

    calls = []
    monkeypatch.setattr(ux_bridge, "progress", lambda *a, **k: calls.append((a, k)))
    spawned = []
    monkeypatch.setattr(
        ux_bridge.threading, "Thread", lambda *a, **k: spawned.append((a, k))
    )
    # Mirrors activity.py's real call: an explicit long hold_s that the
    # farewell branch must override, not just the function's own default.
    ux_bridge.finish_answer(
        "好的，那我就先休息了。如果您需要我，随时可以叫我。",
        source="session:voice-assistant",
        hold_s=60.0,
    )
    assert not spawned, "farewell must not spawn a followup thread"
    assert len(calls) == 1
    (_, kwargs) = calls[0]
    assert kwargs["state"] == "done"
    assert kwargs["ttl_s"] < 12.0


def test_finish_answer_normal_reply_still_spawns_followup(monkeypatch):
    from aipc_agent import ux_bridge

    calls = []
    monkeypatch.setattr(ux_bridge, "progress", lambda *a, **k: calls.append((a, k)))
    spawned = []

    class _FakeThread:
        def __init__(self, *a, **k):
            spawned.append((a, k))

        def start(self):
            pass

    monkeypatch.setattr(ux_bridge.threading, "Thread", _FakeThread)
    ux_bridge.finish_answer("今天台北天氣是晴天，氣溫28度")
    assert spawned, "a normal reply should still get a followup thread"
    assert len(calls) == 1
    assert calls[0][1]["state"] == "done"
    assert calls[0][1]["ttl_s"] >= 12.0
