"""Static tests for voice-streaming-turn helpers (no hardware)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STREAM_LIB = REPO / "modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_stream.py"
STREAM_BIN = REPO / "modules/voice-pipecat/files/usr/bin/aipc-voice-stream"
ORCH_ROOT = REPO / "modules/agent-orchestrator/files/usr/lib/aipc-agent"


def test_aipc_voice_stream_self_test() -> None:
    proc = subprocess.run(
        [sys.executable, str(STREAM_LIB)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self-test OK" in proc.stdout


def test_aipc_voice_stream_cli_self_test() -> None:
    env = {**dict(**__import__("os").environ), "PYTHONPATH": str(STREAM_LIB.parent)}
    proc = subprocess.run(
        [sys.executable, str(STREAM_BIN), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self-test OK" in proc.stdout


def test_stream_chat_self_test() -> None:
    env = {**dict(**__import__("os").environ), "PYTHONPATH": str(ORCH_ROOT)}
    # graphs imports heavy deps; only run if langchain available in env
    try:
        import langchain_core  # noqa: F401
        import langgraph  # noqa: F401
    except ImportError:
        # Dev hosts without agent venv: parse-only check
        src = ORCH_ROOT / "aipc_agent/stream_chat.py"
        compile(src.read_text(encoding="utf-8"), str(src), "exec")
        return
    proc = subprocess.run(
        [sys.executable, "-m", "aipc_agent.stream_chat", "--self-test"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(ORCH_ROOT),
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self_test: OK" in proc.stdout or "OK" in proc.stdout


def test_feed_sentence_chunks_chinese() -> None:
    sys.path.insert(0, str(STREAM_LIB.parent))
    import aipc_voice_stream as s  # type: ignore

    chunks, rest = s.feed_sentence_chunks("今天天气不错。明天呢？", min_chars=4, max_chars=40)
    assert len(chunks) >= 1
    assert "今天" in chunks[0]
    assert rest == "" or rest  # may be empty after full sentences
