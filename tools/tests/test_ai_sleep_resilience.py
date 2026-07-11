"""Suspend/resume resilience artifacts for always-on AI voice stack."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_sleep_script_has_pre_post():
    p = ROOT / "modules/voice-wake/files/var/lib/aipc-voice/bin/aipc-ai-stack-sleep"
    assert p.is_file()
    t = p.read_text()
    assert "pre)" in t and "post)" in t
    assert "aipc-voice-wake" in t
    assert "aipc-voice-overlay" in t
    assert "ensure_denoise" in t or "denoise" in t


def test_sleep_units_shipped():
    pre = ROOT / "modules/voice-wake/files/etc/systemd/system/aipc-ai-sleep-pre.service"
    post = ROOT / "modules/voice-wake/files/etc/systemd/system/aipc-ai-sleep-post.service"
    assert pre.is_file() and post.is_file()
    assert "WantedBy=sleep.target" in pre.read_text()
    assert "ExecStop=" in post.read_text()


def test_wake_reconnects_mic_in_source():
    w = (
        ROOT / "modules/voice-wake/files/usr/lib/aipc-voice/aipc_voice_wake.py"
    ).read_text()
    assert "mic reconnected" in w
    assert "mic-reconnect" in w
