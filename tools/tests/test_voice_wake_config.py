from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_wake_capture_denoise_is_not_reenabled_by_a_unit_override():
    paths = [
        ROOT / "modules/voice-wake/files/etc/systemd/system/aipc-voice-wake.service",
        *(
            ROOT / "modules/voice-wake/files/etc/systemd/system/aipc-voice-wake.service.d"
        ).glob("*.conf"),
        Path("/etc/systemd/system/aipc-voice-wake.service"),
        *Path("/etc/systemd/system/aipc-voice-wake.service.d").glob("*.conf"),
    ]
    text = "\n".join(p.read_text(encoding="utf-8") for p in paths if p.is_file())
    assert "Environment=AIPC_WAKE_DENOISE=1" not in text


def test_wake_policy_env_is_shipped_and_referenced():
    """Single policy file for arm/thrash/reprompt (config truth)."""
    policy = ROOT / "modules/voice-wake/files/etc/aipc/voice/wake-policy.env"
    unit = ROOT / "modules/voice-wake/files/etc/systemd/system/aipc-voice-wake.service"
    assert policy.is_file()
    text = policy.read_text(encoding="utf-8")
    assert "AIPC_WAKE_ALLOW_FUZZY_PROMOTE=0" in text
    assert "AIPC_WAKE_MISS_BACKOFF_BASE=" in text
    u = unit.read_text(encoding="utf-8")
    assert "wake-policy.env" in u
    assert "ExecStartPre=+" in u  # root mkdir /run/aipc
