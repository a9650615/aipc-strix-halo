"""Shared voice UX contract used by aipc CLI + overlay + wake."""
from __future__ import annotations

from pathlib import Path

from aipc_lib import voice_ux


def test_write_read_status_roundtrip(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "aipc-voice-state.json"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    # status_path uses XDG_RUNTIME_DIR
    written = voice_ux.write_status("thinking", "hello", partial="hello")
    assert written.name == "aipc-voice-state.json"
    st = voice_ux.read_status()
    assert st.state == "thinking"
    assert st.detail == "hello"
    assert st.partial == "hello"
    assert "思考" in st.label or "thinking" in st.label.lower() or st.label


def test_known_states_cover_siri_flow() -> None:
    for s in ("listening", "wake", "recording", "thinking", "speaking", "done"):
        assert s in voice_ux.KNOWN_STATES


def test_format_ux_line_contains_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    voice_ux.write_status("recording", "")
    line = voice_ux.format_ux_line()
    assert "recording" in line


def test_voice_cli_ux_get(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from aipc_lib import cli

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    voice_ux.write_status("listening", "")
    result = CliRunner().invoke(cli.main, ["voice", "ux", "get"])
    assert result.exit_code == 0
    assert "listening" in result.output


def test_voice_cli_ux_set(tmp_path: Path, monkeypatch) -> None:
    from click.testing import CliRunner

    from aipc_lib import cli

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AIPC_VOICE_UX_NOTIFY", "0")
    monkeypatch.setenv("AIPC_VOICE_UX_CUE", "0")
    result = CliRunner().invoke(cli.main, ["voice", "ux", "set", "thinking", "demo"])
    assert result.exit_code == 0
    st = voice_ux.read_status()
    assert st.state == "thinking"
    assert st.detail == "demo"
