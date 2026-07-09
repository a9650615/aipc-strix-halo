"""Drive the shipped aipc-voice-once --self-test entry point (closed-loop defaults)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VOICE_ONCE = REPO / "modules" / "voice-pipecat" / "files" / "usr" / "bin" / "aipc-voice-once"


def test_voice_once_self_test_exits_zero_with_closed_loop_defaults() -> None:
    assert VOICE_ONCE.is_file()
    env = os.environ.copy()
    env.pop("AIPC_VOICE_USE_AGGREGATOR", None)
    proc = subprocess.run(
        [sys.executable, str(VOICE_ONCE), "--self-test"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "self-test OK" in proc.stdout
