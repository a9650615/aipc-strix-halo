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
