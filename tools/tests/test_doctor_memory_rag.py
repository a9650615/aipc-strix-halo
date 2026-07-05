from __future__ import annotations

from pathlib import Path

import pytest

from aipc_lib import doctor


class _FakeCompletedProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_check_active_backend_missing_file_returns_none(tmp_path: Path) -> None:
    assert doctor.check_active_backend(tmp_path / "nope") is None


def test_check_active_backend_unknown_value_fails(tmp_path: Path) -> None:
    f = tmp_path / "backend"
    f.write_text("mystery-backend")
    result = doctor.check_active_backend(f)
    assert result.status == doctor.STATUS_FAIL
    assert "unknown backend" in result.message


def test_check_active_backend_matches_active_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "backend"
    f.write_text("pgvector\n")
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(0))
    result = doctor.check_active_backend(f)
    assert result.status == doctor.STATUS_OK


def test_check_active_backend_declared_but_inactive_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "backend"
    f.write_text("qdrant")
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(3))
    result = doctor.check_active_backend(f)
    assert result.status == doctor.STATUS_FAIL
    assert "qdrant.service is not active" in result.message


def test_check_vector_count_returns_none_when_unreachable() -> None:
    # psycopg2 isn't installed in the tools/ venv (rag-ingest's own venv
    # carries it, see modules/rag-ingest/requirements.txt) — this exercises
    # the same "not installed yet" path a fresh/non-hardware doctor run hits.
    assert doctor.check_vector_count() is None
