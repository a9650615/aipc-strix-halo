"""Closed-loop product contract tests — drive shipped entrypoints/helpers.

Acceptance (goal closed-loop): hear→think→speak→remember→manage defaults,
orchestrator consumer URL, mem0 soft-fail, portal intent, volume policy,
status probes for all five stages. No live mic required.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
VOICE_ONCE = ROOT / "modules/voice-pipecat/files/usr/bin/aipc-voice-once"
VOICE_TTS = ROOT / "modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_tts.py"
AGENT = ROOT / "modules/agent-orchestrator/files/usr/lib/aipc-agent"
SELINUX_TE = ROOT / "modules/agent-orchestrator/selinux/aipc_agent_network.te"
SELINUX_PP = (
    ROOT
    / "modules/agent-orchestrator/files/usr/share/selinux/packages/aipc_agent_network.pp"
)

sys.path.insert(0, str(TOOLS))


def test_voice_once_self_test_closed_loop_defaults() -> None:
    proc = subprocess.run(
        [sys.executable, str(VOICE_ONCE), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
        env={k: v for k, v in os.environ.items() if k != "AIPC_VOICE_USE_AGGREGATOR"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self-test OK" in proc.stdout
    src = VOICE_ONCE.read_text(encoding="utf-8")
    assert 'AIPC_VOICE_CHAT_URL", "http://127.0.0.1:4100/chat"' in src
    assert 'AIPC_VOICE_USE_AGGREGATOR", "0"' in src
    # Consumer must not hardcode Lemonade/Ollama as chat URL default
    assert "127.0.0.1:8001" not in src.split("CHAT_URL")[0] + src.split("CHAT_URL")[1][:120]
    assert "11434" not in src.split("def chat")[0] if "def chat" in src else True


def test_tts_self_test_and_no_master_volume_in_tts_module() -> None:
    proc = subprocess.run(
        [sys.executable, str(VOICE_TTS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self-test OK" in proc.stdout
    src = VOICE_TTS.read_text(encoding="utf-8")
    # TTS may set sink-input volume; must not call set-sink-volume for master
    assert "set-sink-volume" not in src or "set-sink-input-volume" in src


def test_master_volume_blocked_by_voice_audio() -> None:
    from aipc_lib.voice_audio import _is_forbidden_master_volume_cmd

    assert _is_forbidden_master_volume_cmd(
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "50%"]
    )
    assert not _is_forbidden_master_volume_cmd(
        ["pactl", "set-sink-input-volume", "42", "100%"]
    )


def test_portal_open_intent_phrases() -> None:
    from aipc_lib.portal import matches_open_portal_intent

    assert matches_open_portal_intent("打开 dashboard")
    assert matches_open_portal_intent("open portal")
    assert matches_open_portal_intent("打開管理介面")
    assert matches_open_portal_intent("打开 dashashboard。")
    assert not matches_open_portal_intent("今天天气怎么样")


def test_voice_ops_baseline_probes_include_five_stages() -> None:
    from aipc_lib import voice_ops

    # Use mocked unit/http so test is offline-safe but drives real function
    def unit_active(name: str) -> str:
        return "active"

    def cont(name: str) -> str:
        return "running"

    def probe(url: str, timeout: float = 2.0) -> tuple[bool, str]:
        return True, "200 mocked"

    def resident() -> voice_ops.Probe:
        return voice_ops.Probe("resident-small", "mocked", True)

    probes = voice_ops.collect_baseline_status(
        unit_active=unit_active,
        cont_status=cont,
        probe_http=probe,
        resident=resident,
    )
    names = {p.name for p in probes}
    for required in ("sensevoice", "chat", "kokoro", "mem0", "portal", "litellm"):
        assert required in names, f"missing probe {required} in {names}"
    text = voice_ops.format_status(probes)
    assert "sensevoice" in text and "mem0" in text and "portal" in text
    assert "ok" in text or "!!" in text


def test_memory_soft_fail_and_selinux_gatekeeper_in_policy() -> None:
    path = AGENT / "aipc_agent/memory.py"
    spec = importlib.util.spec_from_file_location("memory_cl", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old = mod.ENDPOINT
    mod.ENDPOINT = "http://127.0.0.1:9"
    assert mod.recall("x", "voice-session") == ""
    mod.remember("y", "voice-session")  # must not raise
    mod.ENDPOINT = old
    te = SELINUX_TE.read_text(encoding="utf-8")
    assert "gatekeeper_port_t" in te
    assert "name_connect" in te
    assert SELINUX_PP.is_file() and SELINUX_PP.stat().st_size > 0


def test_models_yaml_has_resident_small() -> None:
    models = (
        ROOT / "modules/llm-models/files/etc/aipc/models/models.yaml"
    ).read_text(encoding="utf-8")
    assert "alias: resident-small" in models
    # Closed loop brain is lemonade FLM path (documented in models.yaml)
    assert "resident-small" in models and "lemonade" in models


def test_voice_stream_self_test_if_present() -> None:
    stream = ROOT / "modules/voice-pipecat/files/usr/bin/aipc-voice-stream"
    if not stream.is_file():
        pytest.skip("stream worker not in tree")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "modules/voice-pipecat/files/usr/lib/aipc-voice")
    proc = subprocess.run(
        [sys.executable, str(stream), "--self-test"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self-test OK" in proc.stdout


def test_once_source_parses() -> None:
    ast.parse(VOICE_ONCE.read_text(encoding="utf-8"))
