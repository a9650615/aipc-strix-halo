"""Background learning queue — never blocks the voice /chat return path.

Jobs: skill extract from successful turns, optional deferred crawl-learn.
A single daemon worker drains the queue so many async threads do not pile up.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# Default ON — skill extract must never block TTS; queue is the default path.
ENABLED = os.environ.get("AIPC_LEARN_BG", "1") not in ("0", "false", "no", "off")
MAX_QUEUE = int(os.environ.get("AIPC_LEARN_QUEUE_MAX", "64"))

_q: queue.Queue = queue.Queue(maxsize=max(8, MAX_QUEUE))
_started = False
_lock = threading.Lock()
_stats = {"enqueued": 0, "done": 0, "dropped": 0, "errors": 0}


@dataclass
class LearnJob:
    kind: str  # skill_extract | episode_batch
    payload: dict[str, Any] = field(default_factory=dict)
    enqueued_ts: float = field(default_factory=time.time)


def stats() -> dict[str, Any]:
    return {
        **_stats,
        "qsize": _q.qsize(),
        "enabled": ENABLED,
        "worker": _started,
    }


def _ensure_worker() -> None:
    global _started
    if not ENABLED:
        return
    with _lock:
        if _started:
            return
        _started = True
        th = threading.Thread(target=_worker_loop, name="aipc-learn-bg", daemon=True)
        th.start()
        print("aipc-agent: background learn worker started", flush=True)


def enqueue(job: LearnJob) -> bool:
    """Non-blocking enqueue. Returns False if disabled or queue full."""
    if not ENABLED:
        return False
    _ensure_worker()
    try:
        _q.put_nowait(job)
        _stats["enqueued"] += 1
        return True
    except queue.Full:
        _stats["dropped"] += 1
        print("aipc-agent: learn queue full, drop job", flush=True)
        return False


def enqueue_skill_extract(
    user: str,
    reply: str,
    *,
    session_id: str = "",
    kind: str = "hermes",
    agent: str = "hermes",
    trail: str = "",
) -> bool:
    return enqueue(
        LearnJob(
            kind="skill_extract",
            payload={
                "user": user,
                "reply": reply,
                "session_id": session_id,
                "kind": kind,
                "agent": agent,
                "trail": trail or "",
            },
        )
    )


def _worker_loop() -> None:
    while True:
        try:
            job: LearnJob = _q.get()
        except Exception:
            time.sleep(0.5)
            continue
        try:
            _dispatch(job)
            _stats["done"] += 1
        except Exception as exc:  # noqa: BLE001
            _stats["errors"] += 1
            print(f"aipc-agent: learn worker error: {exc}", flush=True)
        finally:
            try:
                _q.task_done()
            except Exception:
                pass


def _dispatch(job: LearnJob) -> None:
    if job.kind == "skill_extract":
        from aipc_agent.skill_learn import _learn_sync

        p = job.payload
        t0 = time.monotonic()
        meta = _learn_sync(
            str(p.get("user") or ""),
            str(p.get("reply") or ""),
            session_id=str(p.get("session_id") or ""),
            kind=str(p.get("kind") or "hermes"),
            agent=str(p.get("agent") or "hermes"),
            trail=str(p.get("trail") or ""),
        )
        dt = time.monotonic() - t0
        if meta:
            print(
                f"aipc-agent: bg skill-learn ok id={meta.get('id')} {dt:.1f}s",
                flush=True,
            )
        else:
            print(f"aipc-agent: bg skill-learn skip {dt:.1f}s", flush=True)
        return
    if job.kind == "episode_batch":
        from aipc_agent.self_improve import run_episode_backfill

        n = run_episode_backfill(
            max_items=int(job.payload.get("max_items") or 20),
            hours=float(job.payload.get("hours") or 48),
        )
        print(f"aipc-agent: bg episode backfill learned≈{n}", flush=True)
        return
    print(f"aipc-agent: learn unknown job kind={job.kind}", flush=True)
