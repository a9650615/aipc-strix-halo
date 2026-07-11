"""Generic background task registry — any worker (Hermes, daily tools, …).

Long-running flow is decided by the supervisor *dispatch* step (which tool +
short|long), not by hard-coding Hermes. Workers submit callables here when
mode=long; voice gets an immediate spoken ack and a desktop notify on finish.

Mid-run: workers call ``job_update`` (or rely on the heartbeat ticker) so the
overlay and "任务进度" can show *what* is being thought / done.
"""

from __future__ import annotations

import contextvars
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()

# Thread/context of the worker so hermes/daily can push progress without
# plumbing job_id through every call.
_CURRENT_JOB_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aipc_task_job_id", default=None
)

# Keep finished jobs for status queries (voice "任务进度")
_MAX_JOBS = int(os.environ.get("AIPC_TASK_JOBS_MAX", "50"))
_PROGRESS_MAX = int(os.environ.get("AIPC_TASK_PROGRESS_MAX", "40"))
_HEARTBEAT_S = float(os.environ.get("AIPC_TASK_HEARTBEAT_S", "4.0"))

_WORKER_LABELS = {
    "hermes": "Hermes 工具代理",
    "daily_assistant": "日曆/搜尋/用量助手",
    "coder": "编码助手",
}


def worker_label(worker: str) -> str:
    return _WORKER_LABELS.get(worker, worker or "助手")


def current_job_id() -> str | None:
    return _CURRENT_JOB_ID.get()


def _store_path() -> str:
    # Read fresh each call (not cached at import) so tests can monkeypatch
    # AIPC_TASK_JOBS_STORE per-test even though this module is imported once.
    return os.environ.get("AIPC_TASK_JOBS_STORE", "/var/lib/aipc-agent/task_jobs.json")


def _load_store() -> None:
    """Populate _JOBS from disk. Best-effort — a read failure never crashes a turn."""
    path = _store_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent task_jobs: store load failed ({path}): {exc}", flush=True)
        return
    if not isinstance(data, dict):
        return
    with _JOBS_LOCK:
        _JOBS.update(data)


def _save_store_locked() -> None:
    """Atomic write of _JOBS to disk. Caller must hold _JOBS_LOCK."""
    path = _store_path()
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = f"{path}.tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_JOBS, f)
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 — persistence must never break a turn
        print(f"aipc-agent task_jobs: store save failed ({path}): {exc}", flush=True)


# Populate the in-memory cache from any prior run so job_list/format_status_speech
# survive an orchestrator restart.
_load_store()


def _primary_user_home() -> tuple[str, str]:
    user = os.environ.get("AIPC_HERMES_USER") or os.environ.get("AIPC_PRIMARY_USER") or ""
    home = os.environ.get("AIPC_HERMES_HOME") or ""
    if user and home:
        return user, home
    try:
        import pwd

        if user:
            return user, pwd.getpwnam(user).pw_dir
        uids = [int(d) for d in os.listdir("/run/user") if d.isdigit() and int(d) >= 1000]
        if uids:
            pw = pwd.getpwuid(min(uids))
            return pw.pw_name, pw.pw_dir
    except (OSError, KeyError, ValueError, ImportError):
        pass
    return os.environ.get("USER") or "birdyo", os.environ.get("HOME") or str(
        __import__("pathlib").Path.home()
    )


def _notify_desktop(title: str, body: str) -> None:
    """Native notify-send fallback. Prefer glass overlay when alive.

    Callers should already gate on AIPC_DESKTOP_NOTIFY / overlay_alive; this
    is a last-resort bubble for when the HUD is not running.
    """
    try:
        from aipc_agent import ux_bridge

        if ux_bridge.overlay_alive():
            # Still push text to HUD if caller only used this helper
            try:
                ux_bridge.finish_answer(
                    (body or "")[:2500],
                    source="desktop-notify-fallback",
                    hold_s=60.0,
                )
            except Exception:
                pass
            return
    except Exception:
        pass
    try:
        user, home = _primary_user_home()
        env = os.environ.copy()
        env["HOME"] = home
        env["USER"] = user
        try:
            import pwd

            uid = str(pwd.getpwnam(user).pw_uid)
            xdg = f"/run/user/{uid}"
            if os.path.isdir(xdg):
                env["XDG_RUNTIME_DIR"] = xdg
                env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={xdg}/bus")
        except (KeyError, ImportError):
            pass
        lim = int(os.environ.get("AIPC_NOTIFY_BODY_CHARS", "320"))
        argv = [
            "notify-send",
            "--app-name=AIPC",
            "-t",
            "12000",
            title,
            (body or "")[: max(80, lim)],
        ]
        if os.geteuid() == 0 and user and user != "root":
            argv = ["runuser", "-u", user, "--", *argv]
        subprocess.run(argv, env=env, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def job_get(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        return dict(j) if j else None


def job_list(limit: int = 20) -> list[dict[str, Any]]:
    with _JOBS_LOCK:
        items = sorted(
            _JOBS.values(), key=lambda x: float(x.get("started") or 0), reverse=True
        )
        return [dict(x) for x in items[: max(1, limit)]]


def _trim_jobs() -> None:
    if len(_JOBS) <= _MAX_JOBS:
        return
    ordered = sorted(_JOBS.items(), key=lambda kv: float(kv[1].get("started") or 0))
    for jid, _ in ordered[: max(0, len(_JOBS) - _MAX_JOBS)]:
        _JOBS.pop(jid, None)


def job_update(
    detail: str,
    *,
    job_id: str | None = None,
    thinking: str = "",
    state: str = "working",
    push_ux: bool = True,
) -> None:
    """Record mid-run progress / thinking for a job (or current context job)."""
    jid = job_id or current_job_id()
    if not jid:
        if push_ux:
            try:
                from aipc_agent import ux_bridge

                ux_bridge.progress(
                    (thinking or detail or "處理中…")[:120],
                    state=state,
                    source="task-job",
                )
            except Exception:
                pass
        return
    detail_s = (detail or "").strip()[:160]
    think_s = (thinking or detail_s).strip()[:200]
    now = time.time()
    worker = ""
    started = now
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if not j or j.get("status") != "running":
            return
        worker = str(j.get("worker") or "")
        started = float(j.get("started") or now)
        j["detail"] = detail_s or j.get("detail") or ""
        j["last_progress"] = think_s or detail_s
        j["updated"] = now
        prog = list(j.get("progress") or [])
        entry = {"ts": now, "detail": detail_s, "thinking": think_s}
        # de-dupe consecutive identical lines
        if (
            not prog
            or prog[-1].get("thinking") != think_s
            or prog[-1].get("detail") != detail_s
        ):
            prog.append(entry)
            if len(prog) > _PROGRESS_MAX:
                prog = prog[-_PROGRESS_MAX:]
            j["progress"] = prog
        _JOBS[jid] = j
        _save_store_locked()
    if push_ux:
        try:
            from aipc_agent import ux_bridge

            label = worker_label(worker)
            elapsed = now - started
            msg = think_s or detail_s or "處理中…"
            line = f"[{label}] {msg}（{elapsed:.0f}s）"[:120]
            ux_bridge.progress(
                line,
                state=state,
                source=f"job-{jid}",
            )
        except Exception:
            line = (think_s or detail_s or "處理中…")[:120]
        try:
            from aipc_agent import activity, session_registry

            sid = ""
            with _JOBS_LOCK:
                j2 = _JOBS.get(jid) or {}
                sid = str(j2.get("session_id") or "")
            if sid:
                session_registry.touch(
                    sid, status="working", activity=line, job_id=jid
                )
                # Overlay already updated via ux_bridge; never spam native notify
                activity.publish(
                    sid,
                    line,
                    state=state,
                    phase=detail_s[:40],
                    job_id=jid,
                    notify=False,
                )
        except Exception:
            pass


def format_status_speech(limit: int = 5) -> str:
    """Spoken / text summary for voice「任务进度」."""
    jobs = job_list(limit=limit)
    if not jobs:
        return "目前没有后台长任务在跑。"
    parts: list[str] = []
    now = time.time()
    for j in jobs:
        jid = j.get("job_id") or "?"
        worker = worker_label(str(j.get("worker") or "?"))
        st = j.get("status") or "?"
        started = float(j.get("started") or now)
        if st == "running":
            age = max(0.0, now - started)
            last = (j.get("last_progress") or j.get("detail") or "处理中")[:50]
            parts.append(f"{jid} {worker}：运行中 {age:.0f}秒，最近：{last}")
        elif st == "interrupted":
            preview = (j.get("result_text") or "")[:50]
            parts.append(f"有一个任务上次中断了 — {jid} {worker}：{preview}")
        else:
            preview = (j.get("result_text") or j.get("text") or "")[:50]
            parts.append(f"{jid} {worker}：{st} — {preview}")
    return "后台任务：\n" + "\n".join(parts)


def submit(
    worker: str,
    text: str,
    session_id: str,
    fn: Callable[[], dict[str, Any]],
    *,
    plan_summary: str = "",
    grace_s: float = 0.0,
) -> dict[str, Any]:
    """Run ``fn`` in a daemon thread. Returns spoken ack + job_id immediately.

    ``fn`` must return ``{status, text, detail?}`` like other bridges.
    While running, ``current_job_id()`` is set so workers can ``job_update``.

    ``grace_s > 0``: wait up to ``grace_s`` seconds for ``fn`` to finish before
    falling back to the async ack. If it finishes in time, return its full
    result dict unchanged (as an inline call would) and suppress the
    background completion notify/memory-internalize for this job — the
    caller already got the answer synchronously and will handle it itself.
    """
    job_id = str(uuid.uuid4())[:12]
    started = time.time()
    wlabel = worker_label(worker)
    summary = (plan_summary or text or "")[:80]
    with _JOBS_LOCK:
        _trim_jobs()
        _JOBS[job_id] = {
            "job_id": job_id,
            "worker": worker,
            "status": "running",
            "text": (text or "")[:200],
            "session_id": session_id,
            "started": started,
            "updated": started,
            "result_text": "",
            "detail": "started",
            "last_progress": plan_summary or "已派发，准备开始…",
            "progress": [
                {
                    "ts": started,
                    "detail": "started",
                    "thinking": plan_summary or "已派发，准备开始…",
                }
            ],
            "plan_summary": plan_summary or "",
            "pid": None,
            "pgid": None,
            "result_status": "",
            "needs_followup": False,
        }
        _save_store_locked()

    # Bind open session → working + first activity line
    try:
        from aipc_agent import activity, session_registry

        session_registry.open_or_resume(session_id, source="job")
        session_registry.bind_job(
            session_id, job_id, activity=plan_summary or f"{wlabel} 已派發…"
        )
        activity.publish(
            session_id,
            f"[{wlabel}] {summary or '已派發…'}"[:120],
            state="working",
            phase="started",
            job_id=job_id,
            notify=True,
            force_notify=True,
        )
    except Exception:
        pass

    stop_hb = threading.Event()
    result_ready = threading.Event()
    claim_done = threading.Event()
    raw_result_box: dict[str, Any] = {}

    def _heartbeat() -> None:
        phases = (
            "还在处理…",
            "思考与工具执行中…",
            "整理中间结果…",
            "继续推进任务…",
        )
        n = 0
        while not stop_hb.wait(_HEARTBEAT_S):
            n += 1
            with _JOBS_LOCK:
                j = _JOBS.get(job_id)
                if not j or j.get("status") != "running":
                    return
                last_u = float(j.get("updated") or 0)
            # Only heartbeat if worker has been quiet
            if time.time() - last_u < _HEARTBEAT_S * 0.9:
                continue
            job_update(
                phases[min(n - 1, len(phases) - 1)],
                job_id=job_id,
                thinking=phases[min(n - 1, len(phases) - 1)],
                push_ux=True,
            )

    def _worker() -> None:
        token = _CURRENT_JOB_ID.set(job_id)
        try:
            job_update("开始执行…", job_id=job_id, thinking=f"{wlabel} 启动", push_ux=True)
            result = fn() or {}
        except Exception as exc:  # noqa: BLE001
            result = {
                "status": "error",
                "text": f"长任务失败：{exc}",
                "detail": str(exc),
            }
        finally:
            stop_hb.set()
            _CURRENT_JOB_ID.reset(token)
        raw_result_box["result"] = result
        status = str(result.get("status") or "error")
        answer = str(result.get("text") or "").strip() or "长任务已结束。"
        with _JOBS_LOCK:
            prev = _JOBS.get(job_id) or {}
            prog = list(prev.get("progress") or [])
            prog.append(
                {
                    "ts": time.time(),
                    "detail": str(result.get("detail") or status),
                    "thinking": "完成" if status == "ok" else f"结束：{status}",
                }
            )
            _JOBS[job_id] = {
                "job_id": job_id,
                "worker": worker,
                "status": status,
                "text": (text or "")[:200],
                "session_id": session_id,
                "started": started,
                "finished": time.time(),
                "updated": time.time(),
                "result_text": answer[:2000],
                "detail": str(result.get("detail") or ""),
                "last_progress": answer[:120],
                "progress": prog[-_PROGRESS_MAX:],
                "plan_summary": prev.get("plan_summary") or "",
                "delivered_inline": prev.get("delivered_inline", False),
                "pid": prev.get("pid"),
                "pgid": prev.get("pgid"),
                "result_status": status,
                "needs_followup": False,
            }
            _save_store_locked()
        if grace_s > 0:
            # Give the grace-waiter in submit() a brief window to claim
            # inline delivery before we decide whether to notify.
            result_ready.set()
            claim_done.wait(timeout=0.2)
        with _JOBS_LOCK:
            delivered = bool((_JOBS.get(job_id) or {}).get("delivered_inline"))
        if delivered:
            # Answer already went back synchronously to the caller; no
            # duplicate HUD notify / memory-internalize for this job.
            return
        title = "AIPC · 长任务完成" if status == "ok" else "AIPC · 长任务结束"
        try:
            from aipc_agent import activity

            # Glass HUD full answer; native notify only if overlay down
            activity.complete_notify(
                session_id,
                title,
                f"[{wlabel}] {answer}",
                feedback_hint=(status == "ok" and bool(answer)),
            )
        except Exception:
            try:
                from aipc_agent import ux_bridge

                ux_bridge.finish_answer(
                    f"[{wlabel}] {(answer or '')[:2500]}",
                    source=f"job-{worker}",
                    hold_s=75.0,
                )
            except Exception:
                _notify_desktop(title, f"[{wlabel}] {answer}")
        if status == "ok":
            try:
                from aipc_agent import memory

                lane = (
                    memory.AGENT_HERMES
                    if worker == "hermes"
                    else memory.AGENT_DAILY
                    if worker == "daily_assistant"
                    else memory.AGENT_JOBS
                )
                memory.internalize(
                    text[:200],
                    answer[:800],
                    session_id,
                    agent=lane,
                    kind=f"job-{worker}",
                )
            except Exception:
                pass

    threading.Thread(target=_heartbeat, name=f"task-hb-{job_id}", daemon=True).start()
    threading.Thread(target=_worker, name=f"task-job-{worker}-{job_id}", daemon=True).start()

    if grace_s > 0 and result_ready.wait(grace_s):
        with _JOBS_LOCK:
            j = _JOBS.get(job_id)
            if j is not None:
                j["delivered_inline"] = True
        claim_done.set()
        return dict(raw_result_box.get("result") or {"status": "error", "text": ""})

    try:
        from aipc_agent import ux_bridge

        ux_bridge.progress(
            f"长任务已派发 → {wlabel}",
            state="working",
            source=f"job-{worker}",
        )
    except Exception:
        pass
    task_snip = summary or (text or "")[:40]
    return {
        "status": "accepted",
        "job_id": job_id,
        "worker": worker,
        "text": (
            f"好的，我让{wlabel}在后台处理（编号 {job_id}）：{task_snip}。"
            "我会在界面更新进度；完成后会通知你，也可以随时问我任务进度。"
        ),
        "detail": "background",
        "plan_summary": plan_summary or "",
    }


def async_enabled() -> bool:
    return os.environ.get("AIPC_TASK_ASYNC", "1") not in ("0", "false", "no")


def register_proc(pid: int) -> None:
    """Record a spawned worker subprocess's pid/pgid on the current job.

    Called right after a bridge's ``Popen`` succeeds. No-op if there is no
    current job (e.g. an inline, non-submitted call) — safe to call always.
    """
    jid = current_job_id()
    if not jid:
        return
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        pgid = pid
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if not j:
            return
        j["pid"] = pid
        j["pgid"] = pgid
        _JOBS[jid] = j
        _save_store_locked()


def _cmdline_contains(pid: int, needle: str) -> bool:
    """PID-reuse sanity guard: only true if /proc/<pid>/cmdline still mentions
    ``needle``. Prevents killing an unrelated process that happens to have
    reused a dead job's pid after a restart."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
    except OSError:
        return False
    cmd = raw.replace(b"\x00", b" ").decode("utf-8", "replace")
    return needle in cmd


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _killpg_wait(pgid: int, grace: float = 3.0) -> None:
    """SIGTERM then SIGKILL a process group; never raises."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        except (PermissionError, OSError):
            return
        time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def reap_orphans_on_startup() -> None:
    """Call exactly once when the orchestrator process boots.

    A freshly-started process owns no running jobs yet, so any job persisted
    with status=="running" is left over from a dead/previous orchestrator.
    If its subprocess is still alive (and still looks like hermes — the
    pid-reuse guard), kill its whole process group so it cannot run forever
    as an orphan. Always mark the job "interrupted" either way.
    """
    with _JOBS_LOCK:
        running = [dict(j) for j in _JOBS.values() if j.get("status") == "running"]
    for j in running:
        jid = j.get("job_id")
        pid = j.get("pid")
        pgid = j.get("pgid")
        if pid:
            try:
                pid_i = int(pid)
            except (TypeError, ValueError):
                pid_i = None
            if pid_i is not None and _pid_alive(pid_i) and _cmdline_contains(pid_i, "hermes"):
                try:
                    pgid_i = int(pgid) if pgid else pid_i
                    _killpg_wait(pgid_i)
                except Exception as exc:  # noqa: BLE001 — never abort the reap loop
                    print(
                        f"aipc-agent task_jobs: orphan reap failed jid={jid}: {exc}",
                        flush=True,
                    )
        with _JOBS_LOCK:
            cur = _JOBS.get(jid)
            if not cur:
                continue
            now = time.time()
            cur["status"] = "interrupted"
            cur["result_status"] = "interrupted"
            cur["result_text"] = "任务在重启时中断"
            cur["needs_followup"] = True
            cur["updated"] = now
            cur["finished"] = now
            _JOBS[jid] = cur
    with _JOBS_LOCK:
        _save_store_locked()
