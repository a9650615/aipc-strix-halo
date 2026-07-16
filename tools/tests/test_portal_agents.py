from __future__ import annotations

import json
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

PORTAL_LIB = Path(__file__).parents[2] / "modules/system-aipc-portal/files/usr/lib/aipc-portal"
sys.path.insert(0, str(PORTAL_LIB))

from aipc_portal import agents, server  # noqa: E402


def _mk_hermes(tmp: Path) -> Path:
    hermes = tmp / ".hermes"
    (hermes / "logs").mkdir(parents=True)
    (hermes / "logs" / "agent.log").write_text(
        "line keep\n[deleg_abc] tool terminal ok\nnoise\n",
        encoding="utf-8",
    )
    state = hermes / "state.db"
    con = sqlite3.connect(state)
    con.execute(
        """
        CREATE TABLE async_delegations (
          delegation_id TEXT PRIMARY KEY,
          origin_session TEXT,
          origin_ui_session_id TEXT,
          parent_session_id TEXT,
          state TEXT,
          dispatched_at REAL,
          completed_at REAL,
          updated_at REAL,
          event_json TEXT,
          result_json TEXT,
          delivery_state TEXT,
          delivery_attempts INTEGER,
          delivered_at REAL,
          owner_pid INTEGER,
          owner_started_at REAL,
          task_json TEXT,
          delivery_claim TEXT,
          delivery_claimed_at REAL
        )
        """
    )
    con.execute(
        """
        INSERT INTO async_delegations VALUES (
          'deleg_abc', 'sess1', '', 'sess1', 'running', 100.0, NULL, 101.0,
          '{"goal":"do work","status":"running"}',
          '{"results":[{"summary":"half done","model":"coder-agentic","tool_trace":[{"tool":"terminal","status":"ok"}]}],"total_duration_seconds":12}',
          'pending', 0, NULL, 42, NULL,
          '{"goal":"do work","role":"leaf"}', NULL, NULL
        )
        """
    )
    con.commit()
    con.close()

    kanban = hermes / "kanban.db"
    con = sqlite3.connect(kanban)
    con.execute(
        """
        CREATE TABLE tasks (
          id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT, status TEXT,
          priority INTEGER, created_by TEXT, created_at REAL, started_at REAL,
          completed_at REAL, workspace_kind TEXT, workspace_path TEXT,
          branch_name TEXT, project_id TEXT, claim_lock TEXT, claim_expires REAL,
          tenant TEXT, result TEXT, idempotency_key TEXT, consecutive_failures INTEGER,
          worker_pid INTEGER, last_failure_error TEXT, max_runtime_seconds INTEGER,
          last_heartbeat_at REAL, current_run_id INTEGER, workflow_template_id TEXT,
          current_step_key TEXT, skills TEXT, model_override TEXT, max_retries INTEGER,
          goal_mode TEXT, goal_max_turns INTEGER, session_id TEXT, block_kind TEXT,
          block_recurrences TEXT
        )
        """
    )
    con.execute(
        """
        INSERT INTO tasks (
          id, title, body, assignee, status, priority, created_by, created_at,
          workspace_path, branch_name, worker_pid, session_id
        ) VALUES (
          't_one', 'Write doc', 'body here', 'codex', 'ready', 0, 'user', 50.0,
          '/tmp/ws', 'feat/x', NULL, NULL
        )
        """
    )
    con.execute(
        "CREATE TABLE task_comments (id INTEGER PRIMARY KEY, task_id TEXT, author TEXT, body TEXT, created_at REAL)"
    )
    con.execute(
        "CREATE TABLE task_events (id INTEGER PRIMARY KEY, task_id TEXT, run_id INTEGER, kind TEXT, payload TEXT, created_at REAL)"
    )
    con.commit()
    con.close()
    return hermes


def test_resolve_hermes_home_prefers_env(tmp_path: Path) -> None:
    hermes = _mk_hermes(tmp_path / "u")
    found = agents.resolve_hermes_home({"AIPC_HERMES_HOME": str(hermes)}, home_roots=[])
    assert found == hermes


def test_agents_snapshot_reads_delegations_and_kanban(tmp_path: Path) -> None:
    hermes = _mk_hermes(tmp_path / "u")
    snap = agents.agents_snapshot(hermes=hermes, proc_root=tmp_path / "emptyproc")
    assert snap["availability"] == "available"
    assert snap["counts"]["delegations"] == 1
    assert snap["delegations"][0]["id"] == "deleg_abc"
    assert snap["delegations"][0]["state"] == "running"
    assert "do work" in snap["delegations"][0]["goal_preview"]
    assert snap["kanban"][0]["id"] == "t_one"
    assert snap["kanban"][0]["status"] == "ready"


def test_get_delegation_includes_logs(tmp_path: Path) -> None:
    hermes = _mk_hermes(tmp_path / "u")
    detail = agents.get_delegation(hermes, "deleg_abc")
    assert detail is not None
    assert detail["goal"] == "do work"
    assert any("deleg_abc" in (row.get("line") or "") for row in detail["logs"])


def test_missing_hermes_is_empty_not_error(tmp_path: Path) -> None:
    snap = agents.agents_snapshot(hermes=tmp_path / "nope", proc_root=tmp_path / "p")
    assert snap["availability"] == "unavailable"
    assert snap["delegations"] == []
    assert snap["kanban"] == []


def test_enrich_process_task_from_kanban_pid() -> None:
    proc = {"pid": 4242, "provider": "codex", "cmd": "codex", "cwd": "/tmp"}
    kanban = {
        4242: {
            "source": "kanban",
            "kind": "delegated",
            "title": "Write docs",
            "goal_preview": "Write the README",
            "task_id": "t_1",
        }
    }
    out = agents.enrich_process_task(proc, hermes=None, kanban_by_pid=kanban, deleg_by_pid={})
    assert out["task"]["source"] == "kanban"
    assert out["task"]["title"] == "Write docs"


def test_session_task_from_dir(tmp_path: Path) -> None:
    session = tmp_path / "sess1"
    session.mkdir()
    (session / "summary.json").write_text(
        json.dumps(
            {
                "generated_title": "Fix Type-A detection",
                "session_summary": "USB Type-A ports on device card",
                "info": {"id": "sess1"},
                "current_model_id": "grok-4.5",
            }
        ),
        encoding="utf-8",
    )
    (session / "goal").mkdir()
    (session / "goal" / "plan.md").write_text("# Plan: ship Type-A detection\n\nbody\n", encoding="utf-8")
    task = agents._session_task_from_dir(session)
    assert task is not None
    assert "Type-A" in task["title"] or "ship Type-A" in (task.get("goal_preview") or "")
    assert task["source"] == "grok-session"


def test_portal_agents_api_routes(tmp_path: Path, monkeypatch) -> None:
    hermes = _mk_hermes(tmp_path / "u")
    static = tmp_path / "static"
    (static / "agents").mkdir(parents=True)
    (static / "agents" / "index.html").write_text("<h1>Agents</h1>", encoding="utf-8")
    monkeypatch.setattr(server, "STATIC_ROOT", static)
    monkeypatch.setattr(server, "resolve_hermes_home", lambda: hermes)
    monkeypatch.setattr(
        server,
        "agents_snapshot",
        lambda: agents.agents_snapshot(hermes=hermes, proc_root=tmp_path / "p"),
    )
    monkeypatch.setattr(server, "get_delegation", lambda _h, i: agents.get_delegation(hermes, i))
    monkeypatch.setattr(server, "get_kanban", lambda _h, i: agents.get_kanban(hermes, i))
    monkeypatch.setattr(server, "log_tail", lambda _h, query="", limit=120: agents.log_tail(hermes, query=query, limit=limit))

    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    try:
        assert urllib.request.urlopen(f"{base}/agents").read() == b"<h1>Agents</h1>"
        snap = json.load(urllib.request.urlopen(f"{base}/api/v1/agents"))
        assert snap["delegations"][0]["id"] == "deleg_abc"
        detail = json.load(urllib.request.urlopen(f"{base}/api/v1/agents/delegations/deleg_abc"))
        assert detail["id"] == "deleg_abc"
        kanban = json.load(urllib.request.urlopen(f"{base}/api/v1/agents/kanban/t_one"))
        assert kanban["title"] == "Write doc"
        logs = json.load(urllib.request.urlopen(f"{base}/api/v1/agents/logs?q=deleg_abc"))
        assert logs["logs"]
        try:
            urllib.request.urlopen(f"{base}/api/v1/agents/delegations/missing_id")
            raised = False
        except urllib.error.HTTPError as err:
            raised = err.code == 404
        assert raised
    finally:
        httpd.shutdown()
        thread.join()
