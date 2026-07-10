"""Generic background task registry — any worker (Hermes, daily tools, …).

Long-running flow is decided by the supervisor *dispatch* step (which tool +
short|long), not by hard-coding Hermes. Workers submit callables here when
mode=long; voice gets an immediate spoken ack and a desktop notify on finish.

Mid-run: workers call ``job_update`` (or rely on the heartbeat ticker) so the
overlay and "任务进度" can show *what* is being thought / done.
"""

from __future__ import annotations

import contextvars
import os
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
        argv = ["notify-send", "--app-name=AIPC", "-t", "12000", title, (body or "")[:200]]
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
                activity.publish(
                    sid,
                    line,
                    state=state,
                    phase=detail_s[:40],
                    job_id=jid,
                    notify=True,
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
) -> dict[str, Any]:
    """Run ``fn`` in a daemon thread. Returns spoken ack + job_id immediately.

    ``fn`` must return ``{status, text, detail?}`` like other bridges.
    While running, ``current_job_id()`` is set so workers can ``job_update``.
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
        }

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
            }
        try:
            from aipc_agent import ux_bridge

            st = "error" if status != "ok" else "speaking"
            ux_bridge.progress(
                f"[{wlabel}] {answer[:70]}", state=st, source=f"job-{worker}"
            )
        except Exception:
            pass
        title = "AIPC · 长任务完成" if status == "ok" else "AIPC · 长任务结束"
        _notify_desktop(title, f"[{wlabel}] {answer}")
        try:
            from aipc_agent import activity

            # Job done → session back to active (user may follow up), not session-end
            activity.complete_notify(session_id, title, f"[{wlabel}] {answer}")
        except Exception:
            pass
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
