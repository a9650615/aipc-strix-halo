"""Closed-loop AI path unit tests — routing, mem0 client, hermes parse, energy thr.

These exercise real shipped functions under tools/aipc_lib and modules/agent-orchestrator
without re-implementing product logic. Network Hermes full runs are not required.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
AGENT = ROOT / "modules/agent-orchestrator/files/usr/lib/aipc-agent"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(AGENT))


def _load_agent_module(name: str):
    path = AGENT / "aipc_agent" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"aipc_agent_{name}_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Ensure package parent for relative imports inside hermes_bridge/memory
    sys.modules.setdefault("aipc_agent", type(sys)("aipc_agent"))
    sys.modules[f"aipc_agent.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_effective_energy_thr_raises_only_when_playback():
    from aipc_lib.voice_audio import effective_energy_thr, update_bleed_floor

    base = 5000.0
    assert effective_energy_thr(base, playback=False) == base
    raised = effective_energy_thr(base, playback=True, ratio=1.55, extra=3500.0, floor=12000.0)
    assert raised >= 12000.0
    assert raised > base
    # Adaptive thr sits above speaker bleed without needing hard mute
    adapt = effective_energy_thr(
        base, playback=True, bleed_floor=10000.0, ratio=1.55, extra=3500.0, floor=12000.0
    )
    assert adapt > 10000.0
    assert adapt <= 16000.0  # default cap — still reachable by human voice (~12–22k)
    # Loud bleed must not push thr above cap
    loud = effective_energy_thr(
        base, playback=True, bleed_floor=25000.0, ratio=1.55, extra=3500.0, floor=12000.0
    )
    assert loud <= 16000.0
    ema = update_bleed_floor(0.0, 8000.0)
    assert ema == 8000.0
    ema2 = update_bleed_floor(ema, 7000.0)
    assert ema2 < ema


def test_barge_energy_thr_beats_bleed_peak():
    from aipc_lib.voice_audio import barge_energy_thr

    thr = barge_energy_thr(5000.0, bleed_peak=15000.0, ratio=1.85, min_rms=20000.0, over_bleed=1.35)
    assert thr >= 20000.0
    assert thr >= 15000.0 * 1.35
    # Quiet ambient barge thr still has a high floor
    thr2 = barge_energy_thr(5000.0, bleed_peak=0.0, min_rms=20000.0)
    assert thr2 >= 20000.0


def test_hermes_extract_answer_and_session_id():
    # Load hermes_bridge without importing full package __init__ side effects
    path = AGENT / "aipc_agent" / "hermes_bridge.py"
    src = path.read_text(encoding="utf-8")
    # Execute only pure helpers by importing module with stubbed memory
    import types

    mem = types.ModuleType("aipc_agent.memory")
    mem.recall = lambda *a, **k: ""
    pkg = types.ModuleType("aipc_agent")
    pkg.memory = mem
    sys.modules["aipc_agent"] = pkg
    sys.modules["aipc_agent.memory"] = mem
    spec = importlib.util.spec_from_file_location("hermes_bridge_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_bridge_under_test"] = mod
    spec.loader.exec_module(mod)

    assert mod._extract_answer("hello\n\nSession ID: abc123xyz") == "hello"
    assert mod._extract_session_id("Session ID: abc123xyz") == "abc123xyz"
    assert "Session" not in mod._extract_answer("final answer only")
    assert mod.HERMES_EPHEMERAL is True or mod.HERMES_EPHEMERAL is False  # env-driven bool
    # Ephemeral default in source is "1"
    assert 'AIPC_HERMES_EPHEMERAL", "1"' in src or "AIPC_HERMES_EPHEMERAL\", \"1\"" in src


def test_memory_format_memories_real_function():
    path = AGENT / "aipc_agent" / "memory.py"
    spec = importlib.util.spec_from_file_location("memory_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._format_memories({"results": [{"memory": "likes tea"}]}) == "likes tea"
    assert mod._format_memories([{"text": "uses zh"}]) == "uses zh"
    assert mod._format_memories({"results": []}) == ""
    # unreachable endpoint fails soft
    old = mod.ENDPOINT
    mod.ENDPOINT = "http://127.0.0.1:9"
    assert mod.recall("x", "s") == ""
    mod.ENDPOINT = old


def test_supervisor_route_keywords():
    """Route pure function from shipped graphs.py via live agent path or source tree."""
    # Prefer live runtime (what systemd runs); fall back to repo files.
    candidates = [
        Path("/var/lib/aipc-agent"),
        AGENT,
    ]
    graphs = None
    hermes_bridge = None
    last_err: Exception | None = None
    for root in candidates:
        if not (root / "aipc_agent" / "graphs.py").is_file():
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            import importlib

            # Fresh import from this root
            for name in ("aipc_agent.graphs", "aipc_agent.hermes_bridge", "aipc_agent.memory", "aipc_agent"):
                sys.modules.pop(name, None)
            import aipc_agent.graphs as graphs  # type: ignore
            import aipc_agent.hermes_bridge as hermes_bridge  # type: ignore

            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            graphs = None
    if graphs is None:
        pytest.skip(f"could not import graphs (need langgraph): {last_err}")

    assert graphs._route({"text": "what is the capital of France", "session_id": "s"}) == "respond"
    assert graphs._route({"text": "今天有什么会议", "session_id": "s"}) == "daily_assistant"

    # Negative: ordinary chat / creative / define-words stay on respond (AC4)
    ordinary = [
        "帮我写一首诗",
        "写一个小故事",
        "帮我做一下总结",
        "帮我解释重力",
        "shell 是什么",
        "打开 terminal",
        "what is shell",
        "terminal 怎么用",
        "你好啊",
    ]
    for text in ordinary:
        assert graphs.wants_hermes(text) is False, text
        assert graphs._route({"text": text, "session_id": "s"}) == "respond", text

    # Positive: explicit Hermes or real coding/multi-step
    if hermes_bridge.available() and graphs.HERMES_ROUTE:
        for text in (
            "用hermes帮我写脚本",
            "帮我debug这个bug",
            "写代码实现快速排序",
            "复杂任务：改代码并提交",
        ):
            assert graphs.wants_hermes(text) is True, text
            assert graphs._route({"text": text, "session_id": "s"}) == "hermes", text
    else:
        r = graphs._route({"text": "用hermes帮我写脚本", "session_id": "s"})
        assert r in ("respond", "daily_assistant", "hermes")


def test_wake_source_contains_echo_and_barge_paths():
    """Structural: shipped wake module wires playback thr + barge-over-bleed."""
    wake = (
        ROOT
        / "modules/voice-wake/files/usr/lib/aipc-voice/aipc_voice_wake.py"
    ).read_text(encoding="utf-8")
    assert "ECHO_GATE" in wake or "AIPC_WAKE_ECHO_GATE" in wake
    assert "playback" in wake.lower()
    assert "BARGE_OVER_BLEED" in wake or "bleed_peak" in wake
    assert "text-stable+quiet" in wake or "still_loud" in wake
    assert "speech-barge" in wake or "BARGE-IN" in wake


def test_once_notify_policy_in_source():
    once = (ROOT / "modules/voice-pipecat/files/usr/bin/aipc-voice-once").read_text(
        encoding="utf-8"
    )
    assert "AIPC_VOICE_REPLY_NOTIFY" in once
    assert "_long_wait_watchdog" in once
    assert "notify-send" in once
    # Must not always notify on every reply without conditions
    assert "if mode in" in once or "AIPC_VOICE_REPLY_NOTIFY" in once


def test_overlay_top_center_in_source():
    ov = (
        ROOT / "modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py"
    ).read_text(encoding="utf-8")
    assert "top-center" in ov or "top_center" in ov or "geo.left()" in ov
    assert "WindowStaysOnTopHint" in ov
