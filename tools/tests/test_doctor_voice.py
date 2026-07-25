from __future__ import annotations

from pathlib import Path

from aipc_lib import doctor


class _FakeCompletedProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_check_voice_once_fails_when_script_missing(tmp_path: Path) -> None:
    results = doctor.check_voice_once(script=tmp_path / "missing")
    assert results == [
        doctor.Result(
            module="voice-pipecat",
            status=doctor.STATUS_FAIL,
            message=f"{tmp_path / 'missing'} missing or not executable",
        )
    ]


def test_check_voice_once_reports_optional_stt_unit_missing(tmp_path: Path) -> None:
    script = tmp_path / "aipc-voice-once"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)

    results = doctor.check_voice_once(
        script=script,
        stt_unit=tmp_path / "aipc-voice-stt-sensevoice.service",
        notifier="definitely-notify-send-missing",
        runner=lambda *a, **k: _FakeCompletedProcess(3),
    )

    assert results[0] == doctor.Result("voice-pipecat", doctor.STATUS_OK, f"{script} executable")
    assert results[1].module == "voice-stt-sensevoice"
    assert results[1].status == doctor.STATUS_OPTIONAL
    assert "unit not installed" in results[1].message
    assert results[2] == doctor.Result(
        "voice-pipecat-notify",
        doctor.STATUS_WARN,
        "notify-send not found; replies fall back to stdout",
    )


def test_check_voice_once_reports_active_stt_unit(tmp_path: Path) -> None:
    script = tmp_path / "aipc-voice-once"
    unit = tmp_path / "aipc-voice-stt-sensevoice.service"
    script.write_text("#!/bin/sh\nexit 0\n")
    unit.write_text("[Service]\nExecStart=/bin/true\n")
    script.chmod(0o755)

    results = doctor.check_voice_once(
        script=script,
        stt_unit=unit,
        notifier="sh",
        runner=lambda *a, **k: _FakeCompletedProcess(0),
    )

    assert doctor.Result("voice-stt-sensevoice", doctor.STATUS_OK, "aipc-voice-stt-sensevoice.service active") in results


def test_check_voice_wake_fails_on_mangled_auto_arm(tmp_path: Path) -> None:
    policy = tmp_path / "wake-policy.env"
    policy.write_text("AIPC_WAKE_ALLOW_FUZZY_PROMOTE=0\n")
    bad = tmp_path / "aipc_voice_wake.py"
    bad.write_text(
        "# stub\n_MANGLED_WAKE = {'我'}\ndef classify_wake_text():\n    pass\n"
        "def decide_wake_arm():\n    pass\n"
        "def miss_backoff_seconds():\n    pass\n"
        "def junk_capture_action():\n    pass\n"
        "def next_mode_after_empty_capture():\n    pass\n"
        "def effective_wake_policy():\n    pass\n"
    )
    results = doctor.check_voice_wake(
        policy_file=policy,
        live_script=bad,
        ostree_script=tmp_path / "missing-ostree.py",
        unit_name="aipc-voice-wake.service",
        runner=lambda *a, **k: _FakeCompletedProcess(1),
    )
    assert any(r.module == "voice-wake-code" and r.status == doctor.STATUS_FAIL for r in results)


def test_check_voice_wake_ok_on_shipped_helpers(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    wake = root / "modules/voice-wake/files/usr/lib/aipc-voice/aipc_voice_wake.py"
    policy = root / "modules/voice-wake/files/etc/aipc/voice/wake-policy.env"
    results = doctor.check_voice_wake(
        policy_file=policy,
        live_script=wake,
        ostree_script=tmp_path / "no-ostree",
        unit_name="aipc-voice-wake.service",
        runner=lambda *a, **k: _FakeCompletedProcess(1),
    )
    mods = {r.module: r for r in results}
    assert mods["voice-wake-policy"].status == doctor.STATUS_OK
    assert mods["voice-wake-code"].status == doctor.STATUS_OK
    assert mods["voice-wake-unit"].status == doctor.STATUS_OPTIONAL
