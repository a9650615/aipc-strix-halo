from __future__ import annotations

from pathlib import Path

import pytest

from aipc_lib.log_append import ROLES, append_row


@pytest.fixture()
def log_file(tmp_path: Path) -> Path:
    p = tmp_path / "agent-log.md"
    p.write_text(
        "| date | role | model | run label | spec task(s) | sha range | outcome |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 2026-06-28 | 大哥 | opus | prior-run | phase-0#1 | aaa111 | existing row |\n",
        encoding="utf-8",
    )
    return p


def test_append_row_happy_path(log_file: Path) -> None:
    line = append_row(
        date="2026-06-30",
        role="副官",
        model="claude-sonnet-4-6",
        run_label="log-append-2026-06-30",
        spec_tasks="phase-0-foundation#1.1",
        sha_range="abc1234",
        outcome="added log-append helper",
        log_path=log_file,
    )
    assert line == "| 2026-06-30 | 副官 | claude-sonnet-4-6 | log-append-2026-06-30 | phase-0-foundation#1.1 | abc1234 | added log-append helper |\n"
    rows = [l for l in log_file.read_text(encoding="utf-8").splitlines() if l.startswith("| ")]
    assert rows[-1] == line.rstrip()


def test_validation_rejects_bad_date_and_role(log_file: Path) -> None:
    base = dict(model="x", run_label="x", spec_tasks="x", sha_range="x", outcome="x", log_path=log_file)
    with pytest.raises(ValueError, match="role"):
        append_row(date="2026-06-30", role="emperor", **base)
    with pytest.raises(ValueError, match="date"):
        append_row(date="06-30-2026", role="大哥", **base)
    with pytest.raises(ValueError, match="date"):
        append_row(date="not-a-date", role="大哥", **base)
    with pytest.raises(ValueError, match="model"):
        append_row(date="2026-06-30", role="大哥", model="", run_label="x", spec_tasks="x", sha_range="x", outcome="x", log_path=log_file)


def test_existing_rows_untouched(log_file: Path) -> None:
    before = log_file.read_text(encoding="utf-8")
    append_row(
        date="2026-06-30", role="執行兵", model="q", run_label="r",
        spec_tasks="s", sha_range="h", outcome="o", log_path=log_file,
    )
    after = log_file.read_text(encoding="utf-8")
    assert before in after
    diff = after[len(before):]
    added_rows = [l for l in diff.splitlines() if l.startswith("| ")]
    assert len(added_rows) == 1
    assert added_rows[0].startswith("| 2026-06-30")


def test_atomic_rename_no_tmp_linger(log_file: Path) -> None:
    append_row(
        date="2026-06-30", role="副官", model="m", run_label="r",
        spec_tasks="s", sha_range="h", outcome="o", log_path=log_file,
    )
    tmp = log_file.with_name(log_file.name + ".tmp")
    assert not tmp.exists()
    assert log_file.exists()
