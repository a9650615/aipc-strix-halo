"""Controlled official CLI adapters — canary ready, auto-off.

Credentials stay in the provider CLI's user store. No OAuth token copying.
Automatic escalation remains disabled unless policy paid_enabled + explicit grant.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from aipc_agent.router.policy import load_policy

# Feature-detect pins (soft min/max — runtime detection)
CODEX_BIN = os.environ.get("AIPC_CODEX_BIN", "codex")
CLAUDE_BIN = os.environ.get("AIPC_CLAUDE_BIN", "claude")
GROK_BIN = os.environ.get("AIPC_GROK_BIN", "grok")

# Active CLI tasks for cancel/resume (task_id → metadata)
_ACTIVE: dict[str, dict[str, Any]] = {}
_HISTORY: list[dict[str, Any]] = []
_ACTIVE_LOCK = threading.Lock()
_PENDING: dict[str, dict[str, str]] = {}


def _which(name: str) -> str | None:
    return shutil.which(name)


def feature_detect() -> dict[str, Any]:
    """Installed subscription CLIs and structured-output capability."""
    out: dict[str, Any] = {
        "codex": {"installed": False, "path": None, "version": None},
        "claude": {"installed": False, "path": None, "version": None},
        "grok": {"installed": False, "path": None, "version": None},
        "metered_enabled": False,
        "auto_escalation": False,
    }
    pol = load_policy()
    out["metered_enabled"] = bool(pol.get("metered_enabled"))
    out["auto_escalation"] = bool(pol.get("paid_enabled")) and bool(
        pol.get("auto_subscription")
    )
    cx = _which(CODEX_BIN)
    if cx:
        out["codex"]["installed"] = True
        out["codex"]["path"] = cx
        out["codex"]["version"] = _version([cx, "--version"])
    cl = _which(CLAUDE_BIN)
    if cl:
        out["claude"]["installed"] = True
        out["claude"]["path"] = cl
        out["claude"]["version"] = _version([cl, "--version"])
    gx = _which(GROK_BIN)
    if gx:
        out["grok"]["installed"] = True
        out["grok"]["path"] = gx
        out["grok"]["version"] = _version([gx, "--version"])
    return out


def _version(argv: list[str]) -> str | None:
    try:
        r = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        line = (r.stdout or r.stderr or "").strip().splitlines()
        return line[0][:120] if line else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _gate_rpc(payload: dict[str, Any]) -> dict[str, Any]:
    sock = Path(os.environ.get("AIPC_GATE_SOCK", "/run/aipc-agent-gate.sock"))
    if not sock.exists():
        return {}
    try:
        import socket

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1.0)
        client.connect(str(sock))
        client.sendall(json.dumps(payload).encode() + b"\n")
        raw = client.recv(4096)
        client.close()
        result = json.loads(raw.decode() or "{}")
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def session_grant_ok(session_id: str, provider: str) -> bool:
    """Check session-scoped grant via agent-gate when available; else env test hook."""
    if os.environ.get("AIPC_SUBSCRIPTION_GRANT_TEST") == "1":
        return True
    data = _gate_rpc({"cmd": "check", "action": f"subscription.{provider}"})
    return bool(data.get("allowed"))


def ask_once_message(provider: str, data_scopes: list[str]) -> str:
    return (
        f"需要派工给订阅助手（{provider}），这次任务确认一次。"
        f"将发送范围：{', '.join(data_scopes) or 'prompt'}。"
        f"说「同意用{provider}」授权，或「不用了」取消。"
    )


def request_confirmation(
    session_id: str, provider: str, prompt: str, cwd: str
) -> str:
    _PENDING[session_id] = {
        "provider": provider,
        "prompt": prompt,
        "cwd": str(Path(cwd).resolve()),
    }
    return ask_once_message(provider, [f"repo:{Path(cwd).resolve()}"])


def consume_confirmation(session_id: str, text: str) -> dict[str, str] | None:
    pending = _PENDING.get(session_id)
    if not pending:
        return None
    normalized = "".join((text or "").lower().split())
    denied = any(word in normalized for word in ("不用", "取消", "拒绝", "拒絕", "no"))
    approved = any(
        word in normalized
        for word in ("同意", "确认", "確認", "可以", "好", "yes", "approve")
    )
    if denied:
        _PENDING.pop(session_id, None)
        return {"status": "denied"}
    if not approved:
        return None
    provider = pending["provider"].split("-", 1)[0]
    granted = _gate_rpc(
        {
            "cmd": "grant",
            "actions": [f"subscription.{provider}"],
            "scope": "session",
            "duration_seconds": 900,
        }
    )
    if not granted.get("grant_id") and os.environ.get("AIPC_SUBSCRIPTION_GRANT_TEST") != "1":
        return {"status": "gate_unavailable"}
    _PENDING.pop(session_id, None)
    return {"status": "approved", **pending, "grant_id": str(granted.get("grant_id") or "test")}


def revoke_grant(grant_id: str) -> None:
    if grant_id and grant_id != "test":
        _gate_rpc({"cmd": "revoke", "grant_id": grant_id})


def normalize_event(raw: dict[str, Any] | str, *, provider: str) -> dict[str, Any]:
    """Map provider JSON/line into canonical event types."""
    if isinstance(raw, str):
        line = raw.strip()
        if not line:
            return {"type": "progress", "message": "", "provider": provider}
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            return {"type": "output_delta", "text": line, "provider": provider}
    assert isinstance(raw, dict)
    t = str(raw.get("type") or raw.get("event") or "progress").lower()
    mapping = {
        "message": "output_delta",
        "content": "output_delta",
        "delta": "output_delta",
        "tool": "tool_request",
        "tool_use": "tool_request",
        "error": "error",
        "done": "result",
        "result": "result",
        "complete": "result",
        "accepted": "accepted",
        "usage": "usage",
    }
    ctype = mapping.get(t, t if t in mapping.values() else "progress")
    ev: dict[str, Any] = {"type": ctype, "provider": provider}
    if ctype == "output_delta":
        ev["text"] = str(raw.get("text") or raw.get("content") or raw.get("delta") or "")
    elif ctype == "result":
        ev["text"] = str(raw.get("text") or raw.get("result") or raw.get("content") or "")
        ev["artifacts"] = list(raw.get("artifacts") or [])
    elif ctype == "error":
        ev["code"] = str(raw.get("code") or "provider")
        ev["message"] = str(raw.get("message") or raw.get("error") or "")
    elif ctype == "tool_request":
        ev["tool"] = str(raw.get("tool") or raw.get("name") or "unknown")
        ev["risk"] = str(raw.get("risk") or "write")
    elif ctype == "usage":
        ev["quota_kind"] = "subscription"
        ev["units"] = raw.get("units")
    else:
        ev["message"] = str(raw.get("message") or raw.get("phase") or "")[:200]
    return ev


def run_codex_exec(
    prompt: str,
    *,
    cwd: str | None = None,
    deadline_s: float = 120.0,
    dry_run: bool = False,
) -> Iterator[dict[str, Any]]:
    """Start Codex non-interactive if available; yield canonical events."""
    if dry_run or os.environ.get("AIPC_SUBSCRIPTION_DRY_RUN") == "1":
        yield {"type": "accepted", "task_id": "dry-codex", "provider": "codex-subscription"}
        yield {
            "type": "result",
            "text": "(dry-run) codex adapter ready",
            "artifacts": [],
            "provider": "codex-subscription",
        }
        return
    path = _which(CODEX_BIN)
    if not path:
        yield {"type": "error", "code": "provider", "message": "codex not installed", "provider": "codex-subscription"}
        return
    # Prefer documented non-interactive shapes; feature-detect flags lightly
    argv = [path, "exec", "--json", "--sandbox", "workspace-write", "-"]
    yield from _run_cli(argv, _delegation_prompt(prompt), provider="codex-subscription", cwd=cwd, deadline_s=deadline_s)


def run_claude_print(
    prompt: str,
    *,
    cwd: str | None = None,
    deadline_s: float = 120.0,
    dry_run: bool = False,
) -> Iterator[dict[str, Any]]:
    if dry_run or os.environ.get("AIPC_SUBSCRIPTION_DRY_RUN") == "1":
        yield {"type": "accepted", "task_id": "dry-claude", "provider": "claude-subscription"}
        yield {
            "type": "result",
            "text": "(dry-run) claude adapter ready",
            "artifacts": [],
            "provider": "claude-subscription",
        }
        return
    path = _which(CLAUDE_BIN)
    if not path:
        yield {"type": "error", "code": "provider", "message": "claude not installed", "provider": "claude-subscription"}
        return
    argv = [
        path,
        "-p",
        _delegation_prompt(prompt),
        "--output-format",
        "stream-json",
        "--permission-mode",
        "acceptEdits",
    ]
    yield from _run_cli(argv, None, provider="claude-subscription", cwd=cwd, deadline_s=deadline_s)


def run_grok_cli(
    prompt: str,
    *,
    cwd: str | None = None,
    deadline_s: float = 120.0,
    dry_run: bool = False,
) -> Iterator[dict[str, Any]]:
    """Inject one task through the official Grok Build CLI OAuth input layer."""
    if dry_run or os.environ.get("AIPC_SUBSCRIPTION_DRY_RUN") == "1":
        yield {"type": "accepted", "task_id": "dry-grok", "provider": "grok-subscription"}
        yield {
            "type": "result",
            "text": "(dry-run) grok adapter ready",
            "artifacts": [],
            "provider": "grok-subscription",
        }
        return
    path = _which(GROK_BIN)
    if not path:
        yield {"type": "error", "code": "provider", "message": "grok not installed", "provider": "grok-subscription"}
        return
    argv = [
        path,
        "--single",
        _delegation_prompt(prompt),
        "--output-format",
        "streaming-json",
        "--permission-mode",
        "acceptEdits",
        "--cwd",
        cwd or os.getcwd(),
    ]
    yield from _run_cli(argv, None, provider="grok-subscription", cwd=cwd, deadline_s=deadline_s)


def _delegation_prompt(prompt: str) -> str:
    return (
        f"{prompt.strip()}\n\n"
        "Delegation boundary: you may edit files and create commits in this task branch. "
        "Do not push, pull, merge, rebase, publish, or modify remote branches."
    )


def automation_snapshot(*, include_finished: bool = True) -> list[dict[str, Any]]:
    """Redaction-safe state for the local dashboard."""
    now = time.time()
    with _ACTIVE_LOCK:
        rows = [dict(v) for v in _ACTIVE.values()]
        if include_finished:
            rows.extend(dict(v) for v in _HISTORY[-20:])
    safe: list[dict[str, Any]] = []
    for row in rows:
        started = float(row.get("started") or now)
        safe.append(
            {
                "task_id": row.get("task_id"),
                "provider": row.get("provider"),
                "repo": row.get("repo"),
                "branch": row.get("branch"),
                "pid": row.get("pid"),
                "state": row.get("state"),
                "last_activity": row.get("last_activity"),
                "started": started,
                "elapsed_s": round(max(0.0, float(row.get("finished") or now) - started), 1),
                "finished": row.get("finished"),
            }
        )
    return sorted(safe, key=lambda x: float(x.get("started") or 0), reverse=True)


def _branch(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return (result.stdout or "").strip()[:160]
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _guarded_env(env: dict[str, str]) -> tuple[dict[str, str], tempfile.TemporaryDirectory[str]]:
    """Put a git command guard before PATH; commits remain allowed."""
    clean = _scrub_env(env)
    real_git = shutil.which("git", path=clean.get("PATH")) or "/usr/bin/git"
    td = tempfile.TemporaryDirectory(prefix="aipc-cli-guard-")
    wrapper = Path(td.name) / "git"
    wrapper.write_text(
        "#!/bin/sh\n"
        "case \"${1:-}\" in\n"
        "  push|pull|merge|rebase) echo 'aipc policy: remote publication and merge are denied' >&2; exit 126;;\n"
        "esac\n"
        f"exec {real_git} \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    clean["PATH"] = f"{td.name}:{clean.get('PATH', '')}"
    clean["AIPC_DELEGATION_POLICY"] = "commit-allowed;push-merge-denied"
    return clean, td


def _run_cli(
    argv: list[str],
    stdin_text: str | None,
    *,
    provider: str,
    cwd: str | None,
    deadline_s: float,
    task_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    tid = task_id or f"{provider}-{int(time.time())}"
    yield {"type": "accepted", "task_id": tid, "provider": provider}
    workdir = str(Path(cwd or os.getcwd()).resolve())
    guarded_env, guard_tmp = _guarded_env(os.environ.copy())
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if stdin_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=workdir,
            env=guarded_env,
        )
    except OSError as exc:
        yield {"type": "error", "code": "provider", "message": str(exc), "provider": provider}
        return
    with _ACTIVE_LOCK:
        _ACTIVE[tid] = {
            "proc": proc,
            "task_id": tid,
            "provider": provider,
            "repo": workdir,
            "branch": _branch(workdir),
            "pid": proc.pid,
            "state": "running",
            "started": time.time(),
            "last_activity": "CLI input accepted",
        }
    assert proc.stdout is not None
    deadline = time.monotonic() + deadline_s
    buf_text: list[str] = []
    try:
        if stdin_text is not None and proc.stdin:
            proc.stdin.write(stdin_text)
            proc.stdin.close()
        while True:
            if time.monotonic() > deadline:
                proc.kill()
                yield {"type": "error", "code": "timeout", "message": "deadline", "provider": provider, "task_id": tid}
                return
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if not line:
                time.sleep(0.05)
                continue
            ev = normalize_event(line, provider=provider)
            ev["task_id"] = tid
            with _ACTIVE_LOCK:
                if tid in _ACTIVE:
                    _ACTIVE[tid]["last_activity"] = str(
                        ev.get("message") or ev.get("type") or "working"
                    )[:160]
            if ev.get("type") == "output_delta" and ev.get("text"):
                buf_text.append(str(ev["text"]))
            yield ev
        rc = proc.wait(timeout=5)
        if rc != 0 and not buf_text:
            yield {
                "type": "error",
                "code": "provider",
                "message": f"exit {rc}",
                "provider": provider,
                "task_id": tid,
            }
        else:
            yield {
                "type": "result",
                "text": "".join(buf_text) or f"({provider} finished rc={rc})",
                "artifacts": [],
                "provider": provider,
                "task_id": tid,
            }
    except Exception as exc:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:
            pass
        yield {"type": "error", "code": "provider", "message": str(exc), "provider": provider, "task_id": tid}
    finally:
        with _ACTIVE_LOCK:
            done = _ACTIVE.pop(tid, None)
            if done:
                done.pop("proc", None)
                done["state"] = "finished"
                done["finished"] = time.time()
                _HISTORY.append(done)
                del _HISTORY[:-20]
        guard_tmp.cleanup()


def _scrub_env(env: dict[str, str]) -> dict[str, str]:
    """Never inject or log OAuth tokens; strip accidental copies from parent."""
    for k in list(env):
        lk = k.lower()
        if any(x in lk for x in ("oauth", "refresh_token", "client_secret")):
            # Keep PATH etc.; drop secrets that must not hop process boundaries
            if "path" not in lk:
                env.pop(k, None)
    return env


def collect_result(events: Iterator[dict[str, Any]]) -> dict[str, Any]:
    text_parts: list[str] = []
    err = None
    task_id = ""
    for ev in events:
        if ev.get("type") == "accepted":
            task_id = str(ev.get("task_id") or task_id)
        if ev.get("type") == "output_delta":
            text_parts.append(str(ev.get("text") or ""))
        elif ev.get("type") == "result":
            t = str(ev.get("text") or "")
            if t:
                text_parts.append(t)
        elif ev.get("type") == "error":
            err = ev
    if err and not text_parts:
        return {
            "ok": False,
            "text": str(err.get("message") or "error"),
            "events_error": err,
            "task_id": task_id,
        }
    return {
        "ok": True,
        "text": "".join(text_parts).strip(),
        "events_error": err,
        "task_id": task_id,
    }


def cancel(task_id: str) -> dict[str, Any]:
    """Cancel a running subscription CLI task by id (structured terminal event)."""
    tid = (task_id or "").strip()
    with _ACTIVE_LOCK:
        meta = _ACTIVE.pop(tid, None)
    if not meta:
        return {
            "type": "error",
            "code": "provider",
            "message": f"unknown task_id {tid!r}",
            "provider": "subscription",
        }
    proc = meta.get("proc")
    provider = str(meta.get("provider") or "subscription")
    if proc is not None:
        try:
            meta["state"] = "cancelling"
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        except Exception as exc:  # noqa: BLE001
            return {
                "type": "error",
                "code": "provider",
                "message": str(exc),
                "provider": provider,
                "task_id": tid,
            }
    return {
        "type": "result",
        "text": "cancelled",
        "artifacts": [],
        "provider": provider,
        "task_id": tid,
        "cancelled": True,
    }


def resume(
    task_id: str,
    input_text: str,
    *,
    provider: str = "codex-subscription",
    cwd: str | None = None,
    deadline_s: float = 120.0,
    dry_run: bool = False,
) -> Iterator[dict[str, Any]]:
    """Resume a subscription session when the CLI supports it; else re-prompt.

    Yields canonical events. Does not copy credentials.
    """
    tid = (task_id or "").strip()
    yield {
        "type": "accepted",
        "task_id": tid or f"resume-{int(time.time())}",
        "provider": provider,
    }
    if dry_run or os.environ.get("AIPC_SUBSCRIPTION_DRY_RUN") == "1":
        yield {
            "type": "result",
            "text": f"(dry-run) resume {provider} task={tid}",
            "artifacts": [],
            "provider": provider,
            "task_id": tid,
        }
        return
    # Claude: `claude -p --resume <id>`; Codex: `codex exec resume` when present
    if "claude" in provider:
        path = _which(CLAUDE_BIN)
        if not path:
            yield {
                "type": "error",
                "code": "provider",
                "message": "claude not installed",
                "provider": provider,
            }
            return
        argv = [path, "-p", input_text or "", "--output-format", "stream-json"]
        if tid:
            argv.extend(["--resume", tid])
        yield from _run_cli(
            argv, None, provider=provider, cwd=cwd, deadline_s=deadline_s, task_id=tid
        )
        return
    path = _which(CODEX_BIN)
    if not path:
        yield {
            "type": "error",
            "code": "provider",
            "message": "codex not installed",
            "provider": provider,
        }
        return
    # Prefer resume subcommand when available; else fresh exec with prior id in prompt
    argv = [path, "exec", "--json", "-"]
    prompt = input_text or ""
    if tid:
        prompt = f"[resume session {tid}]\n{prompt}"
    yield from _run_cli(
        argv, prompt, provider=provider, cwd=cwd, deadline_s=deadline_s, task_id=tid
    )
