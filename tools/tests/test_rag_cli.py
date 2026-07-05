from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aipc_lib import rag


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


def test_find_source_known() -> None:
    s = rag.find_source("desktop")
    assert s.service == "aipc-rag-desktop.service"
    assert s.default_enabled is True


def test_find_source_unknown_raises() -> None:
    with pytest.raises(KeyError):
        rag.find_source("nope")


def test_list_sources_covers_all_five_units() -> None:
    assert {s.name for s in rag.SOURCES} == {
        "desktop",
        "code",
        "browser-firefox",
        "browser-chrome",
        "screen-audio",
    }


def test_source_status_reports_count_and_active(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_query(sql: str, params: tuple) -> list[tuple]:
        return [(5, "2026-07-06T00:00:00")]

    def fake_runner(cmd, **kwargs):
        return _FakeCompletedProcess(0)

    st = rag.source_status(rag.find_source("desktop"), query_fn=fake_query, runner=fake_runner)
    assert st["vector_count"] == 5
    assert st["active"] is True


def test_source_status_survives_unreachable_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_query(sql: str, params: tuple) -> list[tuple]:
        raise OSError("connection refused")

    def fake_runner(cmd, **kwargs):
        return _FakeCompletedProcess(1)

    st = rag.source_status(rag.find_source("code"), query_fn=failing_query, runner=fake_runner)
    assert st["vector_count"] == 0
    assert st["active"] is False


def test_enable_source_writes_browser_consent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consent_path = tmp_path / "browser-consent.yaml"
    monkeypatch.setattr(rag, "BROWSER_CONSENT", consent_path)

    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    rag.enable_source(rag.find_source("browser-firefox"), runner=fake_runner)

    data = yaml.safe_load(consent_path.read_text())
    assert data["firefox"]["consent"] is True
    assert calls == [["sudo", "systemctl", "enable", "--now", "aipc-rag-browser-firefox.service"]]


def test_disable_source_withdraws_screen_audio_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "screen-audio.yaml"
    config_path.write_text(yaml.safe_dump({"enabled": True, "ttl_days": 7}))
    monkeypatch.setattr(rag, "SCREEN_AUDIO_CONFIG", config_path)

    def fake_runner(cmd, **kwargs):
        return _FakeCompletedProcess(0)

    rag.disable_source(rag.find_source("screen-audio"), runner=fake_runner)

    data = yaml.safe_load(config_path.read_text())
    assert data["enabled"] is False
    assert data["ttl_days"] == 7


def test_enable_source_no_consent_gate_for_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    rag.enable_source(rag.find_source("desktop"), runner=fake_runner)
    assert calls == [["sudo", "systemctl", "enable", "--now", "aipc-rag-desktop.service"]]


def test_reindex_source_deletes_rows_and_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rag, "STATE_DIR", tmp_path)
    state_file = tmp_path / "code.json"
    state_file.write_text("{}")

    queries = []

    def fake_query(sql: str, params: tuple) -> list[tuple]:
        queries.append((sql, params))
        return []

    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    rag.reindex_source(rag.find_source("code"), query_fn=fake_query, runner=fake_runner)

    assert "DELETE FROM rag_chunks" in queries[0][0]
    assert queries[0][1] == ("code",)
    assert not state_file.exists()
    assert calls == [["sudo", "systemctl", "restart", "aipc-rag-code.service"]]


def test_purge_source_returns_deleted_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag, "STATE_DIR", tmp_path)

    def fake_query(sql: str, params: tuple) -> list[tuple]:
        return [(1,), (2,), (3,)]

    n = rag.purge_source(rag.find_source("desktop"), query_fn=fake_query)
    assert n == 3
