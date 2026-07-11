"""aipc-voice-once timing wiring: emits a record, never breaks the turn.

openspec: voice-latency-instrumentation. No hardware (TTS disabled).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "modules/voice-pipecat/files/usr/bin/aipc-voice-once"
LIB = REPO / "modules/voice-pipecat/files/usr/lib/aipc-voice"


def _load_once():
    sys.path.insert(0, str(LIB))
    loader = SourceFileLoader("aipc_voice_once_mod", str(BIN))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_once_self_test_still_passes() -> None:
    proc = subprocess.run(
        [sys.executable, str(BIN), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self-test OK" in proc.stdout


def test_show_emits_record_with_perceived(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIPC_VOICE_TTS", "0")  # no TTS / no hardware
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    mod = _load_once()
    import aipc_voice_timing as t  # from LIB on sys.path

    tt = t.TurnTimer(path="batch")
    # capture_end 5ms in the past so play_start (marked in show) → positive perceived
    tt.mark("capture_end", ns=t.time.monotonic_ns() - 5_000_000)
    mod._turn_timer = tt

    mod.show("hello world")  # must not raise

    log = tmp_path / "aipc-voice" / "turns.jsonl"
    assert log.exists()
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["path"] == "batch"
    assert rec["perceived_ms"] is not None and rec["perceived_ms"] >= 0
    assert "hello world" not in json.dumps(rec)  # no reply text leaks
    assert mod._turn_timer is None  # cleared after flush


def test_timing_disabled_writes_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AIPC_VOICE_TTS", "0")
    monkeypatch.setenv("AIPC_VOICE_TIMING", "0")  # instrumentation off
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    mod = _load_once()
    import aipc_voice_timing as t

    tt = t.TurnTimer(path="batch")
    tt.mark("capture_end", ns=t.time.monotonic_ns() - 5_000_000)
    mod._turn_timer = tt
    mod.show("hi")  # turn still runs
    assert not (tmp_path / "aipc-voice" / "turns.jsonl").exists()
