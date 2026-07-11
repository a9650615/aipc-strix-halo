"""Idle / background self-improve: scan episodes → local skills / lessons.

Runs as:
  - systemd timer (aipc-self-improve.timer) → oneshot
  - or: python -m aipc_agent.self_improve

Never blocks voice. Never writes into aipc modules/**.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from aipc_agent import skill_learn, skill_store

EPISODE_DIR = Path(os.environ.get("AIPC_EPISODE_DIR", "/var/lib/aipc-agent/episodes"))
LEARN_STATE = Path(
    os.environ.get(
        "AIPC_LEARN_STATE",
        "/var/lib/aipc-agent/learning/self_improve_state.json",
    )
)
MAX_PER_RUN = int(os.environ.get("AIPC_SELF_IMPROVE_MAX", "15"))


def _load_state() -> dict[str, Any]:
    if not LEARN_STATE.is_file():
        return {"seen_task_ids": [], "last_run_ts": 0}
    try:
        data = json.loads(LEARN_STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"seen_task_ids": [], "last_run_ts": 0}
    except (OSError, json.JSONDecodeError):
        return {"seen_task_ids": [], "last_run_ts": 0}


def _save_state(state: dict[str, Any]) -> None:
    try:
        LEARN_STATE.parent.mkdir(parents=True, exist_ok=True)
        # keep seen list bounded
        seen = list(state.get("seen_task_ids") or [])[-500:]
        state = {**state, "seen_task_ids": seen, "last_run_ts": time.time()}
        tmp = LEARN_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(LEARN_STATE)
    except OSError as exc:
        print(f"aipc-self-improve: state save fail: {exc}", flush=True)


def _iter_recent_episodes(*, hours: float = 48.0) -> list[dict[str, Any]]:
    if not EPISODE_DIR.is_dir():
        return []
    cutoff = time.time() - hours * 3600
    rows: list[dict[str, Any]] = []
    files = sorted(EPISODE_DIR.glob("episodes-*.jsonl"), reverse=True)[:5]
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            # skip skill_learned meta rows
            if obj.get("kind") == "skill_learned":
                continue
            ts = float(obj.get("ts") or 0)
            if ts and ts < cutoff:
                continue
            if (obj.get("outcome") or "ok") not in ("ok", "success"):
                continue
            user = (obj.get("user") or "").strip()
            reply = (obj.get("reply") or obj.get("text") or "").strip()
            if not user or not reply:
                continue
            rows.append(obj)
    # oldest first so we learn in chronological order
    rows.sort(key=lambda r: float(r.get("ts") or 0))
    return rows


def run_episode_backfill(*, max_items: int = 0, hours: float = 48.0) -> int:
    """Process recent successful episodes not yet learned. Returns learn count."""
    max_items = max_items or MAX_PER_RUN
    state = _load_state()
    seen = set(state.get("seen_task_ids") or [])
    learned = 0
    for ep in _iter_recent_episodes(hours=hours):
        if learned >= max_items:
            break
        tid = str(ep.get("task_id") or "")
        key = tid or f"{ep.get('session_id')}:{ep.get('ts')}:{ep.get('user', '')[:40]}"
        if key in seen:
            continue
        user = str(ep.get("user") or "")
        reply = str(ep.get("reply") or ep.get("text") or "")
        kind = str(ep.get("target") or "respond")
        # map episode target to learn kind
        if kind not in ("hermes", "daily", "respond", "daily_assistant", "coder"):
            kind = "respond"
        if kind == "daily_assistant":
            kind = "daily"
        meta = skill_learn._learn_sync(
            user,
            reply,
            session_id=str(ep.get("session_id") or ""),
            kind=kind if kind != "daily_assistant" else "daily",
            agent=kind,
            trail=str(ep.get("learn_trail") or ep.get("trail") or ""),
        )
        seen.add(key)
        if meta:
            learned += 1
            print(
                f"aipc-self-improve: learned {meta.get('id')} from task={tid[:12]}",
                flush=True,
            )
        else:
            print(f"aipc-self-improve: skip task={tid[:12]}", flush=True)
    state["seen_task_ids"] = list(seen)
    _save_state(state)
    # surface skill count for ops
    n_skills = len(skill_store.list_skills())
    print(
        f"aipc-self-improve: done learned={learned} skills_on_disk={n_skills}",
        flush=True,
    )
    return learned


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="AIPC background self-improve (local skills)")
    p.add_argument("--hours", type=float, default=48.0)
    p.add_argument("--max", type=int, default=MAX_PER_RUN)
    p.add_argument("--stats", action="store_true", help="print learn queue stats and exit")
    args = p.parse_args(argv)
    if args.stats:
        try:
            from aipc_agent.learn_queue import stats

            print(json.dumps(stats(), indent=2))
        except Exception as exc:
            print(f"stats unavailable: {exc}")
        print(f"skills={len(skill_store.list_skills())}")
        return 0
    n = run_episode_backfill(max_items=args.max, hours=args.hours)
    return 0 if n >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
