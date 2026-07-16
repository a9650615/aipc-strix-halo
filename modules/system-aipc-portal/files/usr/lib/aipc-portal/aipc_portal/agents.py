"""Hermes background-agent fleet snapshot for the Control Center Agents page.

Read-only: state.db async_delegations, kanban.db, peer CLI presence, process
scan, and log tails. Portal may run as root — resolve the desktop user's
~/.hermes rather than Path.home().
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

PEER_NAMES = ("claude", "codex", "grok")

_MCP_NOISE = re.compile(
    r"(mcp-server|mcp_stdio_watchdog|mcp-stdio-watchdog|context-mode|hook-post-tool|spine\.sh)",
    re.I,
)
_PEER_ARGV = re.compile(
    r"(?:^|[\s/])(?P<name>claude|codex|grok)(?:\s|$)",
    re.I,
)


def resolve_hermes_home(
    env: dict[str, str] | None = None,
    *,
    home_roots: list[Path] | None = None,
) -> Path | None:
    env = env if env is not None else os.environ
    for key in ("AIPC_HERMES_HOME", "HERMES_HOME"):
        raw = (env.get(key) or "").strip()
        if raw:
            path = Path(raw).expanduser()
            if path.is_dir():
                return path

    user = (env.get("AIPC_HERMES_USER") or env.get("AIPC_PRIMARY_USER") or "").strip()
    candidates: list[Path] = []
    if user:
        candidates.extend(
            [
                Path(f"/var/home/{user}/.hermes"),
                Path(f"/home/{user}/.hermes"),
            ]
        )

    roots = home_roots or [Path("/var/home"), Path("/home")]
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                hermes = child / ".hermes"
                if hermes.is_dir():
                    candidates.append(hermes)
        except OSError:
            continue

    candidates.append(Path.home() / ".hermes")

    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(path)

    for path in ordered:
        if path.is_dir() and (path / "state.db").is_file():
            return path
    for path in ordered:
        if path.is_dir():
            return path
    return None


def _user_home_from_hermes(hermes: Path | None) -> Path | None:
    if hermes is None:
        return None
    # .../.hermes → parent is the user home
    try:
        return hermes.parent if hermes.name == ".hermes" else hermes
    except OSError:
        return None


def _connect_ro(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.is_file():
        return None
    try:
        uri = f"file:{db_path}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=1.0)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def _clip(text: str | None, limit: int = 180) -> str:
    s = (text or "").strip().replace("\n", " ")
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _json_obj(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _first_result(result: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    for blob in (result, event):
        rows = blob.get("results")
        if isinstance(rows, list) and rows:
            first = rows[0]
            if isinstance(first, dict):
                return first
    return {}


def _delegation_row(row: sqlite3.Row, *, full: bool = False) -> dict[str, Any]:
    task = _json_obj(row["task_json"] if "task_json" in row.keys() else None)
    event = _json_obj(row["event_json"] if "event_json" in row.keys() else None)
    result = _json_obj(row["result_json"] if "result_json" in row.keys() else None)
    first = _first_result(result, event)
    goal = str(task.get("goal") or event.get("goal") or "")
    model = first.get("model") or task.get("model") or event.get("model")
    tools: list[str] = []
    trace = first.get("tool_trace") if isinstance(first.get("tool_trace"), list) else []
    for step in trace:
        if isinstance(step, dict) and step.get("tool"):
            tools.append(str(step["tool"]))
    summary = str(first.get("summary") or event.get("error") or "")
    state = str(row["state"] or event.get("status") or "unknown")
    duration = (
        result.get("total_duration_seconds")
        or event.get("total_duration_seconds")
        or first.get("duration_seconds")
    )
    out: dict[str, Any] = {
        "id": str(row["delegation_id"]),
        "kind": "delegation",
        "state": state,
        "goal_preview": _clip(goal, 200),
        "summary_preview": _clip(summary, 200),
        "model": model,
        "tools": tools[:12],
        "tool_count": len(tools),
        "origin_session": row["origin_session"] if "origin_session" in row.keys() else None,
        "parent_session_id": row["parent_session_id"] if "parent_session_id" in row.keys() else None,
        "dispatched_at": row["dispatched_at"] if "dispatched_at" in row.keys() else None,
        "completed_at": row["completed_at"] if "completed_at" in row.keys() else None,
        "updated_at": row["updated_at"] if "updated_at" in row.keys() else None,
        "duration_seconds": duration,
        "delivery_state": row["delivery_state"] if "delivery_state" in row.keys() else None,
        "owner_pid": row["owner_pid"] if "owner_pid" in row.keys() else None,
        "role": task.get("role") or event.get("role"),
    }
    if full:
        out["goal"] = goal
        out["summary"] = summary
        out["tool_trace"] = trace
        out["task"] = {
            k: task.get(k)
            for k in ("goals", "context", "toolsets", "role", "model", "is_batch")
            if k in task
        }
        out["event"] = {
            k: event.get(k)
            for k in ("status", "error", "type", "is_batch")
            if k in event
        }
    return out


def list_delegations(hermes: Path | None, *, limit: int = 40) -> list[dict[str, Any]]:
    if hermes is None:
        return []
    con = _connect_ro(hermes / "state.db")
    if con is None:
        return []
    try:
        rows = con.execute(
            """
            SELECT * FROM async_delegations
            ORDER BY COALESCE(updated_at, dispatched_at, 0) DESC
            LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [_delegation_row(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def get_delegation(hermes: Path | None, delegation_id: str) -> dict[str, Any] | None:
    if hermes is None or not delegation_id:
        return None
    con = _connect_ro(hermes / "state.db")
    if con is None:
        return None
    try:
        row = con.execute(
            "SELECT * FROM async_delegations WHERE delegation_id = ?",
            (delegation_id,),
        ).fetchone()
        if row is None:
            return None
        detail = _delegation_row(row, full=True)
        detail["logs"] = log_tail(hermes, query=delegation_id, limit=80)
        if detail.get("origin_session"):
            detail["logs"] = _merge_unique_logs(
                detail["logs"],
                log_tail(hermes, query=str(detail["origin_session"]), limit=40),
            )
        return detail
    except sqlite3.Error:
        return None
    finally:
        con.close()


def list_kanban(hermes: Path | None, *, limit: int = 40) -> list[dict[str, Any]]:
    if hermes is None:
        return []
    con = _connect_ro(hermes / "kanban.db")
    if con is None:
        return []
    try:
        rows = con.execute(
            """
            SELECT id, title, body, assignee, status, priority, created_by,
                   created_at, started_at, completed_at, workspace_kind,
                   workspace_path, branch_name, worker_pid, last_heartbeat_at,
                   current_run_id, session_id, result, last_failure_error
            FROM tasks
            ORDER BY COALESCE(started_at, created_at, 0) DESC
            LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "kind": "kanban",
                    "title": r["title"],
                    "body_preview": _clip(r["body"], 160),
                    "status": r["status"],
                    "assignee": r["assignee"],
                    "priority": r["priority"],
                    "created_by": r["created_by"],
                    "created_at": r["created_at"],
                    "started_at": r["started_at"],
                    "completed_at": r["completed_at"],
                    "workspace_path": r["workspace_path"],
                    "branch_name": r["branch_name"],
                    "worker_pid": r["worker_pid"],
                    "last_heartbeat_at": r["last_heartbeat_at"],
                    "session_id": r["session_id"],
                    "result_preview": _clip(r["result"], 160),
                    "last_failure_error": _clip(r["last_failure_error"], 160),
                }
            )
        return out
    except sqlite3.Error:
        return []
    finally:
        con.close()


def get_kanban(hermes: Path | None, task_id: str) -> dict[str, Any] | None:
    if hermes is None or not task_id:
        return None
    con = _connect_ro(hermes / "kanban.db")
    if con is None:
        return None
    try:
        row = con.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        keys = row.keys()
        detail = {
            "id": row["id"],
            "kind": "kanban",
            "title": row["title"],
            "body": row["body"] if "body" in keys else "",
            "status": row["status"],
            "assignee": row["assignee"] if "assignee" in keys else None,
            "priority": row["priority"] if "priority" in keys else None,
            "workspace_path": row["workspace_path"] if "workspace_path" in keys else None,
            "branch_name": row["branch_name"] if "branch_name" in keys else None,
            "worker_pid": row["worker_pid"] if "worker_pid" in keys else None,
            "session_id": row["session_id"] if "session_id" in keys else None,
            "result": row["result"] if "result" in keys else None,
            "last_failure_error": row["last_failure_error"]
            if "last_failure_error" in keys
            else None,
            "created_at": row["created_at"] if "created_at" in keys else None,
            "started_at": row["started_at"] if "started_at" in keys else None,
            "completed_at": row["completed_at"] if "completed_at" in keys else None,
            "last_heartbeat_at": row["last_heartbeat_at"]
            if "last_heartbeat_at" in keys
            else None,
        }
        try:
            comments = con.execute(
                """
                SELECT id, task_id, author, body, created_at
                FROM task_comments WHERE task_id = ?
                ORDER BY id DESC LIMIT 30
                """,
                (task_id,),
            ).fetchall()
            detail["comments"] = [dict(c) for c in comments]
        except sqlite3.Error:
            detail["comments"] = []
        try:
            events = con.execute(
                """
                SELECT id, task_id, run_id, kind, payload, created_at
                FROM task_events WHERE task_id = ?
                ORDER BY id DESC LIMIT 40
                """,
                (task_id,),
            ).fetchall()
            detail["events"] = [dict(e) for e in events]
        except sqlite3.Error:
            detail["events"] = []
        detail["logs"] = log_tail(hermes, query=task_id, limit=80)
        return detail
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _peer_bin(name: str, user_home: Path | None) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    candidates: list[Path] = []
    if user_home is not None:
        candidates.extend(
            [
                user_home / ".local" / "bin" / name,
                user_home / ".npm-global" / "bin" / name,
                user_home / ".grok" / "bin" / name,
                user_home / "bin" / name,
            ]
        )
    candidates.extend(
        [
            Path(f"/home/linuxbrew/.linuxbrew/bin/{name}"),
            Path(f"/var/home/linuxbrew/.linuxbrew/bin/{name}"),
            Path(f"/usr/local/bin/{name}"),
        ]
    )
    for path in candidates:
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        except OSError:
            continue
    return None


def peer_status(user_home: Path | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    auth_paths = {
        "claude": [
            (user_home / ".claude.json") if user_home else None,
            (user_home / ".config" / "claude" / "auth.json") if user_home else None,
        ],
        "codex": [(user_home / ".codex" / "auth.json") if user_home else None],
        "grok": [(user_home / ".grok" / "auth.json") if user_home else None],
    }
    for name in PEER_NAMES:
        path = _peer_bin(name, user_home)
        auth_present = False
        auth_file = None
        for candidate in auth_paths.get(name, []):
            if candidate is not None and candidate.is_file():
                auth_present = True
                auth_file = str(candidate)
                break
        rows.append(
            {
                "id": name,
                "label": {"claude": "Claude Code", "codex": "Codex", "grok": "Grok"}[name],
                "installed": path is not None,
                "path": path,
                "auth_present": auth_present,
                "auth_file": auth_file,
            }
        )
    return rows


def _read_proc_cmdline(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def _read_proc_etime(pid: int) -> int | None:
    try:
        # field 22 starttime in clock ticks; fall back to etimes via stat mtime delta
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        # comm can contain spaces/parens — split after last ')'
        rest = stat[stat.rfind(")") + 2 :].split()
        start_ticks = int(rest[19])  # starttime
        hz = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK")) if hasattr(os, "sysconf") else 100
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        return max(0, int(uptime - (start_ticks / float(hz or 100))))
    except (OSError, IndexError, ValueError):
        return None


def _read_proc_cwd(pid: int) -> str | None:
    try:
        return str(Path(f"/proc/{pid}/cwd").resolve())
    except OSError:
        return None


def list_peer_processes(proc_root: Path | None = None) -> list[dict[str, Any]]:
    root = proc_root or Path("/proc")
    found: list[dict[str, Any]] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        cmd = _read_proc_cmdline(pid) if proc_root is None else None
        if proc_root is not None:
            # test fixture: cmdline file may exist as text
            cpath = entry / "cmdline"
            if cpath.is_file():
                raw = cpath.read_bytes()
                cmd = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        if not cmd:
            continue
        if _MCP_NOISE.search(cmd):
            continue
        # Skip pure mcp-server peers (not a user task turn).
        if re.search(r"\bmcp-server\b", cmd, re.I):
            continue
        match = _PEER_ARGV.search(cmd)
        if not match:
            continue
        name = match.group("name").lower()
        # Require argv to look like the tool itself, not a random path containing the name.
        # e.g. bare "grok" / "claude ..." / ".../bin/grok" — not "codexbar_usage".
        tokens = cmd.split()
        base0 = Path(tokens[0]).name.lower() if tokens else ""
        if base0 not in PEER_NAMES and not any(
            Path(t).name.lower() in PEER_NAMES for t in tokens[:3]
        ):
            continue
        etime = _read_proc_etime(pid) if proc_root is None else None
        cwd = _read_proc_cwd(pid) if proc_root is None else None
        found.append(
            {
                "pid": pid,
                "provider": name,
                "cmd": _clip(cmd, 240),
                "etime_seconds": etime,
                "cwd": cwd,
            }
        )
    found.sort(key=lambda r: (-(r.get("etime_seconds") or 0), r["pid"]))
    return found


def _read_ppid(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _grok_session_dirs_from_pid(pid: int) -> list[Path]:
    """Session dirs opened by this grok process (via /proc/pid/fd)."""
    fd_root = Path(f"/proc/{pid}/fd")
    found: list[tuple[float, Path]] = []
    try:
        entries = list(fd_root.iterdir())
    except OSError:
        return []
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if "/.grok/sessions/" not in target:
            continue
        # Prefer events.jsonl / summary.json paths → session dir
        path = Path(target)
        if path.name in ("events.jsonl", "summary.json", "hunk_records.jsonl", "chat_history.jsonl"):
            session = path.parent
        elif path.suffix == ".log" and "sessions" in path.parts:
            # .../session/terminal/foo.log
            session = path.parent.parent if path.parent.name == "terminal" else path.parent
        else:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        if session.is_dir():
            found.append((mtime, session))
    # newest first, unique
    seen: set[Path] = set()
    out: list[Path] = []
    for _, session in sorted(found, key=lambda x: -x[0]):
        try:
            key = session.resolve()
        except OSError:
            key = session
        if key in seen:
            continue
        seen.add(key)
        out.append(session)
    return out


def _session_task_from_dir(session: Path) -> dict[str, Any] | None:
    summary_path = session / "summary.json"
    title = None
    summary = None
    session_id = session.name
    model = None
    agent_name = None
    if summary_path.is_file():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        if isinstance(data, dict):
            title = data.get("generated_title") or data.get("session_summary")
            summary = data.get("session_summary")
            info = data.get("info") if isinstance(data.get("info"), dict) else {}
            session_id = str(info.get("id") or session.name)
            model = data.get("current_model_id")
            agent_name = data.get("agent_name")
    # Active goal from goal/plan.md if present
    goal_preview = None
    plan = session / "goal" / "plan.md"
    if plan.is_file():
        try:
            text = plan.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines()[:40]:
                line = line.strip()
                if line.startswith("# "):
                    goal_preview = line.lstrip("# ").strip()
                    break
        except OSError:
            pass
    if not title and not goal_preview and not summary:
        return None
    return {
        "source": "grok-session",
        "kind": "interactive",
        "title": _clip(str(title or goal_preview or summary or session_id), 120),
        "goal_preview": _clip(str(goal_preview or summary or title or ""), 200),
        "session_id": session_id,
        "model": model,
        "agent_name": agent_name,
        "session_path": str(session),
    }


def _kanban_by_pid(hermes: Path | None) -> dict[int, dict[str, Any]]:
    if hermes is None:
        return {}
    con = _connect_ro(hermes / "kanban.db")
    if con is None:
        return {}
    out: dict[int, dict[str, Any]] = {}
    try:
        rows = con.execute(
            """
            SELECT id, title, body, status, assignee, worker_pid, session_id, workspace_path
            FROM tasks
            WHERE worker_pid IS NOT NULL AND worker_pid != 0
            """
        ).fetchall()
        for r in rows:
            try:
                pid = int(r["worker_pid"])
            except (TypeError, ValueError):
                continue
            out[pid] = {
                "source": "kanban",
                "kind": "delegated",
                "title": _clip(str(r["title"] or r["id"]), 120),
                "goal_preview": _clip(str(r["body"] or r["title"] or ""), 200),
                "task_id": r["id"],
                "status": r["status"],
                "assignee": r["assignee"],
                "session_id": r["session_id"],
                "workspace_path": r["workspace_path"],
            }
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return out


def _delegation_by_owner_pid(hermes: Path | None) -> dict[int, dict[str, Any]]:
    if hermes is None:
        return {}
    con = _connect_ro(hermes / "state.db")
    if con is None:
        return {}
    out: dict[int, dict[str, Any]] = {}
    try:
        rows = con.execute(
            """
            SELECT delegation_id, state, owner_pid, task_json, origin_session
            FROM async_delegations
            WHERE owner_pid IS NOT NULL AND owner_pid != 0
            ORDER BY COALESCE(updated_at, dispatched_at, 0) DESC
            """
        ).fetchall()
        for r in rows:
            try:
                pid = int(r["owner_pid"])
            except (TypeError, ValueError):
                continue
            if pid in out:
                continue  # keep newest
            task = _json_obj(r["task_json"])
            goal = str(task.get("goal") or "")
            out[pid] = {
                "source": "hermes-delegation",
                "kind": "delegated",
                "title": _clip(goal or str(r["delegation_id"]), 120),
                "goal_preview": _clip(goal, 200),
                "delegation_id": r["delegation_id"],
                "state": r["state"],
                "origin_session": r["origin_session"] if "origin_session" in r.keys() else None,
            }
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return out


def enrich_process_task(
    proc: dict[str, Any],
    *,
    hermes: Path | None,
    kanban_by_pid: dict[int, dict[str, Any]] | None = None,
    deleg_by_pid: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach best-effort task context to a live peer process."""
    pid = int(proc.get("pid") or 0)
    task: dict[str, Any] | None = None
    # 1) Kanban worker_pid exact match
    if kanban_by_pid and pid in kanban_by_pid:
        task = kanban_by_pid[pid]
    # 2) Hermes delegation owner_pid (parent agent often, not the peer CLI)
    if task is None and deleg_by_pid and pid in deleg_by_pid:
        task = deleg_by_pid[pid]
    # 2b) parent PID match for hermes-owned children
    if task is None and deleg_by_pid:
        ppid = _read_ppid(pid)
        if ppid and ppid in deleg_by_pid:
            task = dict(deleg_by_pid[ppid])
            task["matched_via"] = "parent_pid"
    # 3) Grok interactive session via open FDs + summary.json
    if task is None and proc.get("provider") == "grok":
        sessions = _grok_session_dirs_from_pid(pid)
        for session in sessions[:3]:
            task = _session_task_from_dir(session)
            if task:
                break
    # 4) Claude: session under ~/.claude/projects is harder; leave unknown if no match
    if task is None:
        task = {
            "source": "unknown",
            "kind": "unknown",
            "title": None,
            "goal_preview": None,
            "detail": "no hermes/kanban/session link for this PID",
        }
    proc = dict(proc)
    proc["task"] = task
    return proc


def log_tail(
    hermes: Path | None,
    *,
    query: str = "",
    limit: int = 120,
    files: tuple[str, ...] = ("agent.log", "errors.log"),
) -> list[dict[str, Any]]:
    if hermes is None:
        return []
    limit = max(1, min(int(limit), 500))
    q = (query or "").strip()
    lines: list[dict[str, Any]] = []
    for name in files:
        path = hermes / "logs" / name
        if not path.is_file():
            continue
        try:
            # Read last ~256KB only
            data = path.read_bytes()
            if len(data) > 256_000:
                data = data[-256_000:]
            text = data.decode("utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if q and q not in line:
                continue
            lines.append({"file": name, "line": line})
    return lines[-limit:]


def _merge_unique_logs(
    primary: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in primary + extra:
        key = f"{row.get('file')}:{row.get('line')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out[-200:]


def agents_snapshot(
    *,
    hermes: Path | None = None,
    env: dict[str, str] | None = None,
    proc_root: Path | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    hermes = hermes if hermes is not None else resolve_hermes_home(env)
    user_home = _user_home_from_hermes(hermes)
    peers = peer_status(user_home)
    processes = list_peer_processes(proc_root=proc_root)
    kanban_by_pid = _kanban_by_pid(hermes)
    deleg_by_pid = _delegation_by_owner_pid(hermes)
    processes = [
        enrich_process_task(
            p,
            hermes=hermes,
            kanban_by_pid=kanban_by_pid,
            deleg_by_pid=deleg_by_pid,
        )
        for p in processes
    ]
    # attach running counts onto peers
    counts_by_peer: dict[str, int] = {n: 0 for n in PEER_NAMES}
    for proc in processes:
        provider = str(proc.get("provider") or "")
        if provider in counts_by_peer:
            counts_by_peer[provider] += 1
    for peer in peers:
        peer["running_count"] = counts_by_peer.get(str(peer["id"]), 0)

    delegations = list_delegations(hermes, limit=limit)
    kanban = list_kanban(hermes, limit=limit)

    def _count_state(rows: list[dict[str, Any]], key: str, active: set[str]) -> int:
        return sum(1 for r in rows if str(r.get(key) or "").lower() in active)

    running = _count_state(delegations, "state", {"running", "active", "in_progress"})
    running += _count_state(kanban, "status", {"running", "claimed"})
    running += len(processes)

    availability = "available" if hermes is not None and (hermes / "state.db").is_file() else "unavailable"
    summary_parts = []
    if availability == "available":
        summary_parts.append(f"{len(delegations)} delegations")
        summary_parts.append(f"{len(kanban)} kanban")
        if processes:
            summary_parts.append(f"{len(processes)} live peer procs")
        if running:
            summary_parts.append(f"{running} active signals")
    else:
        summary_parts.append("Hermes home not found")

    return {
        "availability": availability,
        "hermes_home": str(hermes) if hermes else None,
        "generated_at": time.time(),
        "summary": " · ".join(summary_parts),
        "counts": {
            "delegations": len(delegations),
            "kanban": len(kanban),
            "processes": len(processes),
            "running_signals": running,
            "peers_ready": sum(1 for p in peers if p.get("installed") and p.get("auth_present")),
        },
        "peers": peers,
        "processes": processes,
        "delegations": delegations,
        "kanban": kanban,
    }
