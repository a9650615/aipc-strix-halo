"""Streaming worker emits a path=stream latency record (no hardware).

openspec: voice-streaming-turn consuming voice-telemetry.
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "modules/voice-pipecat/files/usr/bin/aipc-voice-stream"
LIB = REPO / "modules/voice-pipecat/files/usr/lib/aipc-voice"


def _load():
    sys.path.insert(0, str(LIB))
    loader = SourceFileLoader("aipc_voice_stream_bin", str(BIN))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


EVENTS = [
    {"event": "session_id", "session_id": "t", "task_id": "1"},
    {"event": "token", "text": "你好。"},
    {"event": "token", "text": "世界。"},
    {"event": "done", "text": "你好。世界。", "task_id": "1"},
]


def test_stream_turn_fills_ttft_and_ttfa() -> None:
    mod = _load()
    import aipc_voice_timing as t

    tt = t.TurnTimer(path="stream")
    tt.mark("capture_end")
    ok, full = mod.run_stream_turn(
        text="hi",
        session_id="s",
        speak=lambda _t: True,
        stream_events=iter(list(EVENTS)),
        timer=tt,
    )
    assert ok, full
    rec = tt.record(ts=None)
    assert rec["path"] == "stream"
    assert rec["llm_ttft_ms"] is not None and rec["llm_ttft_ms"] >= 0
    assert rec["tts_ttfa_ms"] is not None and rec["tts_ttfa_ms"] >= 0
    assert rec["perceived_ms"] is not None and rec["perceived_ms"] >= 0


def test_stream_turn_without_timer_is_unaffected() -> None:
    mod = _load()
    ok, full = mod.run_stream_turn(
        text="hi",
        session_id="s",
        speak=lambda _t: True,
        stream_events=iter(list(EVENTS)),
    )
    assert ok, full
    assert "你好" in full
