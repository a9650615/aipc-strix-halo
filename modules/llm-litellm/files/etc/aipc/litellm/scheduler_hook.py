#!/usr/bin/env python3
"""Gateway memory scheduler (0012): admission control for Lemonade GPU loads.

Mounted into the litellm container as /app/scheduler_hook.py and registered
via litellm_settings.callbacks. Every chat request targeting a local Lemonade
GPU model passes budget/priority admission BEFORE litellm forwards it, so
lemond only ever receives loads that fit physical memory — this is the
structural thrash fix (see openspec/changes/0012-memory-scheduler-coder-122b).

Pure scheduling logic is kept free of litellm/network imports so
`python3 scheduler_hook.py --self-test` runs anywhere.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

MANIFEST_PATH = Path(os.environ.get("AIPC_SCHED_MANIFEST", "/app/models.yaml"))
LEMONADE_BASE = os.environ.get("AIPC_SCHED_LEMONADE", "http://127.0.0.1:8001")
BUDGET_GB = float(os.environ.get("AIPC_SCHED_BUDGET_GB", "96"))
COOLDOWN_S = float(os.environ.get("AIPC_SCHED_COOLDOWN_S", "120"))
HOLD_TIMEOUT_S = float(os.environ.get("AIPC_SCHED_HOLD_TIMEOUT_S", "900"))
POLL_S = float(os.environ.get("AIPC_SCHED_POLL_S", "2"))

TIER_FLOATING = "floating"
TIER_RESIDENT = "resident"
TIER_EXCLUSIVE = "exclusive"


def parse_manifest(data: dict) -> dict[str, dict]:
    """alias -> {model_id, size_gb, tier} for Lemonade GPU models only."""
    out: dict[str, dict] = {}
    for entry in (data.get("models") or []):
        if not isinstance(entry, dict) or entry.get("backend") != "lemonade":
            continue
        if entry.get("pool") == "npu":
            continue
        model_id = entry.get("model_id")
        size = entry.get("size_gb")
        if not model_id or not isinstance(size, (int, float)):
            continue
        out[str(entry.get("alias", model_id))] = {
            "model_id": str(model_id),
            "size_gb": float(size),
            "tier": str(entry.get("tier", TIER_FLOATING)),
        }
    return out


def gpu_loaded(health: dict, manifest: dict[str, dict]) -> list[dict]:
    """Loaded manifest-known GPU models from a lemonade health payload."""
    by_model_id = {spec["model_id"]: spec for spec in manifest.values()}
    out: list[dict] = []
    for entry in health.get("all_models_loaded") or []:
        if not isinstance(entry, dict) or not entry.get("loaded"):
            continue
        model_id = entry.get("model_name") or entry.get("name")
        spec = by_model_id.get(model_id)
        if spec is None:
            continue
        out.append({
            "model_id": model_id,
            "size_gb": spec["size_gb"],
            "tier": spec["tier"],
            "in_use": entry.get("status") == "in_use",
            "last_use": entry.get("last_use") or 0,
        })
    return out


def free_gb(loaded: list[dict], budget_gb: float) -> float:
    return budget_gb - sum(m["size_gb"] for m in loaded)


def pick_victim(
    loaded: list[dict],
    target: dict,
    admitted_at: dict[str, float],
    now: float,
    cooldown_s: float = COOLDOWN_S,
) -> str | None:
    """Next model_id to evict for `target`, or None if nothing is eligible.

    Floating tier before resident tier, oldest last_use first. In-use models
    are never victims. Residents fall only to an exclusive-tier target.
    Cooldown (recently admitted by this scheduler) is bypassed only by an
    exclusive-tier target.
    """
    exclusive = target["tier"] == TIER_EXCLUSIVE

    def eligible(m: dict) -> bool:
        if m["model_id"] == target["model_id"] or m["in_use"]:
            return False
        if m["tier"] == TIER_EXCLUSIVE:
            # An idle exclusive model is released by the idle-release daemon,
            # not preempted mid-session by agent traffic.
            return exclusive
        if m["tier"] == TIER_RESIDENT and not exclusive:
            return False
        if not exclusive and now - admitted_at.get(m["model_id"], 0.0) < cooldown_s:
            return False
        return True

    tier_rank = {TIER_FLOATING: 0, TIER_RESIDENT: 1, TIER_EXCLUSIVE: 2}
    candidates = sorted(
        (m for m in loaded if eligible(m)),
        key=lambda m: (tier_rank.get(m["tier"], 0), m["last_use"]),
    )
    return candidates[0]["model_id"] if candidates else None


class _SchedulerCore:
    """Async admission loop over pluggable health/unload I/O (testable)."""

    def __init__(self, fetch_health, post_unload, budget_gb=BUDGET_GB,
                 cooldown_s=COOLDOWN_S, hold_timeout_s=HOLD_TIMEOUT_S,
                 poll_s=POLL_S, clock=time.monotonic, sleeper=asyncio.sleep):
        self.fetch_health = fetch_health
        self.post_unload = post_unload
        self.budget_gb = budget_gb
        self.cooldown_s = cooldown_s
        self.hold_timeout_s = hold_timeout_s
        self.poll_s = poll_s
        self.clock = clock
        self.sleeper = sleeper
        self.lock = asyncio.Lock()
        self.admitted_at: dict[str, float] = {}

    async def admit(self, alias: str, manifest: dict[str, dict]) -> None:
        """Return when `alias` may be forwarded; raise TimeoutError on hold expiry."""
        target = manifest.get(alias)
        if target is None:
            return
        health = await self.fetch_health()
        if health is None:
            return  # degrade open: scheduler must never become the outage
        loaded = gpu_loaded(health, manifest)
        if any(m["model_id"] == target["model_id"] for m in loaded):
            return  # fast path, no lock
        async with self.lock:
            deadline = self.clock() + self.hold_timeout_s
            while True:
                health = await self.fetch_health()
                if health is None:
                    return
                loaded = gpu_loaded(health, manifest)
                if any(m["model_id"] == target["model_id"] for m in loaded):
                    break
                if free_gb(loaded, self.budget_gb) >= target["size_gb"]:
                    break
                victim = pick_victim(loaded, target, self.admitted_at,
                                     self.clock(), self.cooldown_s)
                if victim is not None:
                    await self.post_unload(victim)
                else:
                    await self.sleeper(self.poll_s)
                if self.clock() > deadline:
                    raise TimeoutError(
                        f"memory scheduler: cannot fit {alias} "
                        f"({target['size_gb']}GB) within {self.budget_gb}GB budget"
                    )
            self.admitted_at[target["model_id"]] = self.clock()


def _load_manifest_file(path: Path) -> dict[str, dict]:
    import yaml

    try:
        return parse_manifest(yaml.safe_load(path.read_text()) or {})
    except (OSError, ValueError):
        return {}


async def _http_health():
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{LEMONADE_BASE}/api/v0/health")
            return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


async def _http_unload(model_id: str) -> None:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(f"{LEMONADE_BASE}/api/v0/unload",
                              json={"model_name": model_id})
    except Exception:
        pass  # next loop iteration re-reads health and retries or holds


try:
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # self-test / render environments
    CustomLogger = object


class MemoryScheduler(CustomLogger):
    def __init__(self):
        self.core = _SchedulerCore(_http_health, _http_unload)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if call_type not in ("completion", "acompletion", "text_completion"):
            return data
        alias = data.get("model")
        if not alias:
            return data
        manifest = _load_manifest_file(MANIFEST_PATH)
        try:
            await self.core.admit(alias, manifest)
        except TimeoutError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail=str(exc))
        return data


scheduler = MemoryScheduler()


def self_test() -> None:
    manifest = parse_manifest({"models": [
        {"alias": "coder-122b", "backend": "lemonade",
         "model_id": "Q122", "size_gb": 59.2, "tier": "exclusive"},
        {"alias": "coder-agentic", "backend": "lemonade",
         "model_id": "Q36", "size_gb": 21.8, "tier": "resident"},
        {"alias": "assistant-gemma", "backend": "lemonade",
         "model_id": "G26", "size_gb": 15.8, "tier": "resident"},
        {"alias": "qwythos-9b", "backend": "lemonade",
         "model_id": "QW9", "size_gb": 5.6, "tier": "resident"},
        {"alias": "ornith-35b", "backend": "lemonade",
         "model_id": "ORN", "size_gb": 26.0},
        {"alias": "resident-small", "backend": "lemonade",
         "model_id": "FLM", "size_gb": 2.5, "pool": "npu"},
        {"alias": "main-cloud", "backend": "anthropic",
         "model_id": "claude", "size_gb": "cloud"},
    ]})
    assert set(manifest) == {"coder-122b", "coder-agentic", "assistant-gemma",
                             "qwythos-9b", "ornith-35b"}
    assert manifest["ornith-35b"]["tier"] == "floating"

    def health_for(ids, in_use=()):
        return {"all_models_loaded": [
            {"model_name": i, "loaded": True, "last_use": n * 1000,
             "status": "in_use" if i in in_use else "idle"}
            for n, i in enumerate(ids)
        ]}

    # Exclusive target evicts floating (oldest) before residents.
    loaded = gpu_loaded(health_for(["Q36", "ORN", "G26"]), manifest)
    assert pick_victim(loaded, manifest["coder-122b"], {}, now=0.0) == "ORN"
    # ...then residents, oldest first.
    loaded = gpu_loaded(health_for(["Q36", "G26"]), manifest)
    assert pick_victim(loaded, manifest["coder-122b"], {}, now=0.0) == "Q36"
    # Non-exclusive target may not evict residents.
    loaded = gpu_loaded(health_for(["Q36", "G26", "QW9"]), manifest)
    assert pick_victim(loaded, manifest["ornith-35b"], {}, now=0.0) is None
    # In-use exclusive model is not a victim for agent traffic.
    loaded = gpu_loaded(health_for(["Q122"], in_use={"Q122"}), manifest)
    assert pick_victim(loaded, manifest["coder-agentic"], {}, now=0.0) is None
    # Cooldown blocks non-exclusive eviction, exclusive bypasses it.
    loaded = gpu_loaded(health_for(["ORN", "QW9"]), manifest)
    recent = {"ORN": 100.0}
    assert pick_victim(loaded, manifest["qwythos-9b"], recent, now=150.0) is None
    assert pick_victim(loaded, manifest["coder-122b"], recent, now=150.0) == "ORN"

    async def run_async_cases():
        # 122B admission: evicts ORN then residents until 59.2 fits in 96.
        state = {"loaded": ["Q36", "ORN", "G26", "QW9"], "unloads": []}

        async def fake_health():
            return health_for(state["loaded"])

        async def fake_unload(model_id):
            state["unloads"].append(model_id)
            state["loaded"].remove(model_id)

        core = _SchedulerCore(fake_health, fake_unload, budget_gb=96,
                              hold_timeout_s=10, poll_s=0)
        await core.admit("coder-122b", manifest)
        # 69.2 loaded -> free 26.8; evict ORN -> 43.4 free? (96-43.2=52.8)
        # keep evicting oldest until >= 59.2 free: ORN, Q36 -> free 74.6.
        assert state["unloads"] == ["ORN", "Q36"], state["unloads"]

        # Fast path: already loaded -> no unloads, no lock contention.
        state2 = {"loaded": ["Q122"], "unloads": []}

        async def health2():
            return health_for(state2["loaded"])

        async def unload2(model_id):
            state2["unloads"].append(model_id)

        core2 = _SchedulerCore(health2, unload2, budget_gb=96)
        await core2.admit("coder-122b", manifest)
        assert state2["unloads"] == []

        # Hold: in-use 122B + gemma request that cannot fit -> TimeoutError.
        state3 = {"loaded": ["Q122", "Q36", "G26"], "unloads": []}

        async def health3():
            return health_for(state3["loaded"], in_use={"Q122", "Q36", "G26"})

        async def unload3(model_id):
            state3["unloads"].append(model_id)

        clock = {"t": 0.0}

        async def instant_sleep(_s):
            clock["t"] += 5.0

        core3 = _SchedulerCore(health3, unload3, budget_gb=96,
                               hold_timeout_s=20, poll_s=0,
                               clock=lambda: clock["t"], sleeper=instant_sleep)
        # ponytail: manifest lacks a model that fits leftover budget here, so
        # assert the hold/timeout path with everything busy instead.
        try:
            await core3.admit("ornith-35b", manifest)
        except TimeoutError:
            pass
        else:
            raise AssertionError("expected hold timeout")
        assert state3["unloads"] == []

        # Degrade open: health unreachable -> admit without action.
        async def health_none():
            return None

        core4 = _SchedulerCore(health_none, unload3, budget_gb=96)
        await core4.admit("coder-122b", manifest)

        # Unknown alias (cloud) passes through.
        await core2.admit("main-cloud", manifest)

    asyncio.run(run_async_cases())
    print("scheduler_hook self-test passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        print("usage: scheduler_hook.py --self-test", file=sys.stderr)
        sys.exit(2)
