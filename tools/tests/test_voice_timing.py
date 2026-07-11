"""Static tests for the voice turn-latency recorder (no hardware).

openspec: voice-latency-instrumentation (capability voice-telemetry).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TIMING_LIB = REPO / "modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_timing.py"


def _load(monkeypatch=None):
    spec = importlib.util.spec_from_file_location("aipc_voice_timing", TIMING_LIB)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_self_test_runs() -> None:
    proc = subprocess.run(
        [sys.executable, str(TIMING_LIB)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self-test OK" in proc.stdout


def test_headline_durations_from_marks() -> None:
    t = _load()
    tt = t.TurnTimer(path="batch")
    ms = 1_000_000  # 1 ms in ns
    tt.mark("capture_end", ns=0)
    tt.mark("tts_request", ns=100 * ms)
    tt.mark("tts_first_audio", ns=150 * ms)
    tt.mark("play_start", ns=200 * ms)
    rec = tt.record(ts=None)
    assert rec["perceived_ms"] == 200.0  # capture_end -> play_start
    assert rec["tts_ttfa_ms"] == 50.0  # tts_request -> tts_first_audio
    assert rec["llm_ttft_ms"] is None  # no llm marks on this batch turn
    assert rec["path"] == "batch"


def test_no_spoken_content_ever_stored() -> None:
    t = _load()
    tt = t.TurnTimer(path="stream")
    # Caller might fat-finger content into context; recorder must drop it.
    tt.context(tts_backend="kokoro", preset="voice", transcript="secret words", reply="the answer")
    tt.mark("capture_end", ns=0)
    tt.mark("play_start", ns=5 * 1_000_000)
    rec = tt.record(ts=None)
    blob = json.dumps(rec, ensure_ascii=False)
    assert "secret words" not in blob
    assert "the answer" not in blob
    assert rec["tts_backend"] == "kokoro"
    assert rec["preset"] == "voice"
    # only known keys are serialized
    allowed = {"ts", "path", "perceived_ms", "llm_ttft_ms", "tts_ttfa_ms", "tts_backend", "preset", "flags"}
    assert set(rec) <= allowed


def test_size_cap_drops_oldest(tmp_path) -> None:
    t = _load()
    log = tmp_path / "turns.jsonl"
    for i in range(5):
        tt = t.TurnTimer(path="batch")
        tt.mark("capture_end", ns=0)
        tt.mark("play_start", ns=(i + 1) * 1_000_000)
        tt.flush(path=str(log), cap=3)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # capped
    perceived = [json.loads(x)["perceived_ms"] for x in lines]
    assert perceived == [3.0, 4.0, 5.0]  # oldest two dropped


def test_disable_flag(tmp_path, monkeypatch) -> None:
    t = _load()
    monkeypatch.setenv("AIPC_VOICE_TIMING", "0")
    log = tmp_path / "turns.jsonl"
    tt = t.TurnTimer(path="batch")
    tt.mark("capture_end", ns=0)
    tt.mark("play_start", ns=1_000_000)
    assert tt.flush(path=str(log)) is None
    assert not log.exists()


def test_flush_never_raises_on_unwritable_path() -> None:
    t = _load()
    tt = t.TurnTimer(path="batch")
    tt.mark("capture_end", ns=0)
    tt.mark("play_start", ns=1_000_000)
    # A path whose parent cannot be created (a file used as a directory).
    bad = str(TIMING_LIB / "nope" / "turns.jsonl")
    assert tt.flush(path=bad) is None  # swallowed, no exception
