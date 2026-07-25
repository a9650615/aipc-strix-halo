from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from aipc_lib.peer_mcp_events import (  # noqa: E402
    append_event,
    clip_output,
    fold_events,
    pid_alive,
    terminal_status,
)


def test_clip_output_scrubs_controls_and_keeps_tail() -> None:
    value = "old\x00\x1b[31mnew\n" + ("x" * 20)
    assert clip_output(value, limit=12) == "xxxxxxxxxxx…"


def test_append_event_creates_user_only_jsonl(tmp_path: Path) -> None:
    event = append_event(
        tmp_path / ".hermes",
        {
            "agent_id": "claude-1",
            "peer": "claude",
            "kind": "started",
            "status": "running",
            "pid": os.getpid(),
        },
    )
    assert event["schema"] == 1
    path = tmp_path / ".hermes" / "peer-agents" / "events.jsonl"
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["agent_id"] == "claude-1"


def test_fold_events_skips_bad_lines_and_keeps_latest(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"agent_id":"a","peer":"codex","kind":"started","status":"running","ts":1,"pid":99}\n'
        "not-json\n"
        '{"agent_id":"a","kind":"output","status":"running","ts":2,"pid":99,"output_tail":"Read file"}\n'
        '{"agent_id":"b","kind":"finished","status":"completed","ts":3,"pid":100}\n',
        encoding="utf-8",
    )
    rows = fold_events(path)
    assert [row["agent_id"] for row in rows] == ["b", "a"]
    assert rows[1]["output_tail"] == "Read file"


def test_terminal_status_maps_stop_and_nonzero() -> None:
    assert terminal_status("stopped") == "stopped"
    assert terminal_status("finished", 0) == "completed"
    assert terminal_status("finished", 1) == "failed"


@pytest.mark.parametrize("pid", [0, -1, "not-a-pid"])
def test_pid_alive_rejects_invalid_pids(pid: object) -> None:
    assert pid_alive(pid) is False
