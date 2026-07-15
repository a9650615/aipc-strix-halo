#!/usr/bin/env python3
"""Gateway Single Memory Owner (SMO) — UMA admission control for Lemonade.

Successor to 0012 memory-scheduler. Every chat request for a local Lemonade
GPU model is admitted HERE before LiteLLM forwards it. Lemonade is the
executor (load/unload/infer); this module is the only policy owner.

Policy (Strix Halo / 121 Gi UMA, hardware-verified thrash 2026-07-16):
  * At most ONE GPU LLM loaded (NPU/FLM resident is out of this pool).
  * exclusive-tier (coder-122b) requires the GPU pool empty of others first.
  * Real gates: static weight ledger + MemAvailable + GTT used.
  * Swap is never a ticket to load a large model (thrash legalization).
  * Global asyncio.Lock serializes all admits that need a load.
  * Idle ComfyUI reclaim runs before giving up (0016).

Pure scheduling logic stays free of litellm/network so
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
# Logical weight budget (GiB). Live quadlet sets 80.
BUDGET_GB = float(os.environ.get("AIPC_SCHED_BUDGET_GB", "80"))
COOLDOWN_S = float(os.environ.get("AIPC_SCHED_COOLDOWN_S", "120"))
HOLD_TIMEOUT_S = float(os.environ.get("AIPC_SCHED_HOLD_TIMEOUT_S", "900"))
POLL_S = float(os.environ.get("AIPC_SCHED_POLL_S", "2"))
# Real-memory headroom: admit only if MemAvailable >= size + headroom.
HEADROOM_GB = float(os.environ.get("AIPC_SCHED_HEADROOM_GB", "12"))
# Hard floor: never admit if MemAvailable below this (even small models).
RAM_FLOOR_GB = float(os.environ.get("AIPC_SCHED_RAM_FLOOR_GB", "12"))
# GPU slot count (non-NPU). UMA policy: 1.
MAX_GPU_LOADED = int(os.environ.get("AIPC_SCHED_MAX_GPU", "1"))
# GTT used upper bound after which we refuse new loads until eviction frees it.
GTT_BUDGET_GB = float(os.environ.get("AIPC_SCHED_GTT_BUDGET_GB", "70"))
# Swap-backed admit is OFF by default (2026-07-16 thrash root cause).
# Set AIPC_SCHED_ALLOW_SWAP_ADMIT=1 only for emergency experiments.
ALLOW_SWAP_ADMIT = os.environ.get("AIPC_SCHED_ALLOW_SWAP_ADMIT", "0") not in ("0", "")
# Even if swap admit is on, never use it for models larger than this (GiB).
SWAP_ADMIT_MAX_SIZE_GB = float(os.environ.get("AIPC_SCHED_SWAP_ADMIT_MAX_SIZE_GB", "8"))
# GPU aliases that may be *loaded* by any client. Everything else is refused
# at the gateway so background services cannot thrash UMA by casually
# warming assistant-gemma / ornith / qwythos. Comma-separated; empty = allow all
# (escape hatch). Default is the deliberate work set only.
# NPU resident-small is not in this list (pool=npu, SMO skips it).
_GPU_ALLOW_RAW = os.environ.get(
    "AIPC_SCHED_GPU_ALLOW",
    "coder-agentic,coder-compact,coder-122b",
)
GPU_ALLOW = {a.strip() for a in _GPU_ALLOW_RAW.split(",") if a.strip()}
# Min seconds between switching to a *different* GPU model (anti-storm).
# Exclusive 122B bypasses. 0 disables.
# Mild anti-storm only; blocked aliases already 403. Hermes needs free
# compact↔agentic switches; 30s was too harsh once allowlist is on.
MIN_GPU_SWITCH_S = float(os.environ.get("AIPC_SCHED_MIN_GPU_SWITCH_S", "5"))
# Workhorse (Hermes default) is never delayed by switch rate-limit.
_WORKHORSE_RAW = os.environ.get("AIPC_SCHED_WORKHORSE", "coder-agentic")
WORKHORSE = {a.strip() for a in _WORKHORSE_RAW.split(",") if a.strip()}
COMFY_BASE = os.environ.get("AIPC_SCHED_COMFY_BASE")
COMFY_RECLAIM = os.environ.get("AIPC_SCHED_COMFY_RECLAIM", "1") not in ("0", "")

TIER_FLOATING = "floating"
TIER_RESIDENT = "resident"
TIER_EXCLUSIVE = "exclusive"

# Host sysfs (podman --network host + host /proc; GTT needs host mount or
# shared sysfs — lemonade/litellm on this box see host /sys via default).
_GTT_PATHS = (
    "/sys/class/drm/card1/device/mem_info_gtt_used",
    "/sys/class/drm/card0/device/mem_info_gtt_used",
)


def mem_available_gb(meminfo_path: str = "/proc/meminfo") -> float | None:
    """Host MemAvailable in GB, or None if unreadable."""
    try:
        for line in open(meminfo_path):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return None


def swap_free_gb(meminfo_path: str = "/proc/meminfo") -> float | None:
    """Host SwapFree in GB, or None if unreadable."""
    try:
        for line in open(meminfo_path):
            if line.startswith("SwapFree:"):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return None


def gtt_used_gb(paths: tuple[str, ...] = _GTT_PATHS) -> float | None:
    """AMD GTT (system RAM used as GPU memory) in GB, or None."""
    for p in paths:
        try:
            return int(open(p).read().strip()) / 1024 / 1024 / 1024
        except (OSError, ValueError):
            continue
    return None


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
        # Optional work profile size (preferred for admission); falls back to size_gb.
        work = entry.get("size_work_gb", size)
        if not isinstance(work, (int, float)):
            work = size
        out[str(entry.get("alias", model_id))] = {
            "model_id": str(model_id),
            "size_gb": float(work),  # admission uses work cost
            "size_full_gb": float(size),
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


def others_loaded(loaded: list[dict], target_id: str) -> list[dict]:
    return [m for m in loaded if m["model_id"] != target_id]


def pick_victim(
    loaded: list[dict],
    target: dict,
    admitted_at: dict[str, float],
    now: float,
    cooldown_s: float = COOLDOWN_S,
) -> str | None:
    """Next model_id to evict for `target`, or None if nothing is eligible.

    Floating before resident, oldest last_use first. In-use never victims.
    Residents fall only to exclusive targets. Exclusive idle models are
    only victims for another exclusive (or same) target — agent traffic
    must wait for idle-release, not pre-empt mid exclusive session.
    """
    exclusive = target["tier"] == TIER_EXCLUSIVE

    def eligible(m: dict) -> bool:
        if m["model_id"] == target["model_id"] or m["in_use"]:
            return False
        if m["tier"] == TIER_EXCLUSIVE:
            return exclusive
        if m["tier"] == TIER_RESIDENT and not exclusive:
            return False
        # Cooldown only for models this scheduler admitted (key present).
        # Missing key must NOT default to epoch 0 — that blocked every victim
        # when now < COOLDOWN_S (and permanently for now=0 in tests).
        if (
            not exclusive
            and m["model_id"] in admitted_at
            and now - admitted_at[m["model_id"]] < cooldown_s
        ):
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

    def __init__(
        self,
        fetch_health,
        post_unload,
        budget_gb=BUDGET_GB,
        cooldown_s=COOLDOWN_S,
        hold_timeout_s=HOLD_TIMEOUT_S,
        poll_s=POLL_S,
        clock=time.monotonic,
        sleeper=asyncio.sleep,
        headroom_gb=HEADROOM_GB,
        mem_available=mem_available_gb,
        ram_floor_gb=RAM_FLOOR_GB,
        swap_free=swap_free_gb,
        gtt_used=gtt_used_gb,
        gtt_budget_gb=GTT_BUDGET_GB,
        max_gpu=MAX_GPU_LOADED,
        allow_swap_admit=ALLOW_SWAP_ADMIT,
        swap_admit_max_size_gb=SWAP_ADMIT_MAX_SIZE_GB,
        comfy_idle=None,
        comfy_reclaim=None,
    ):
        self.fetch_health = fetch_health
        self.post_unload = post_unload
        self.budget_gb = budget_gb
        self.cooldown_s = cooldown_s
        self.hold_timeout_s = hold_timeout_s
        self.poll_s = poll_s
        self.clock = clock
        self.sleeper = sleeper
        self.headroom_gb = headroom_gb
        self.mem_available = mem_available
        self.ram_floor_gb = ram_floor_gb
        self.swap_free = swap_free
        self.gtt_used = gtt_used
        self.gtt_budget_gb = gtt_budget_gb
        self.max_gpu = max_gpu
        self.allow_swap_admit = allow_swap_admit
        self.swap_admit_max_size_gb = swap_admit_max_size_gb
        self.comfy_idle = comfy_idle if comfy_idle is not None else _http_comfy_idle
        self.comfy_reclaim = (
            comfy_reclaim if comfy_reclaim is not None else _http_comfy_reclaim
        )
        self.lock = asyncio.Lock()
        self.admitted_at: dict[str, float] = {}
        self._comfy_reclaimed = False
        self._last_gpu_alias: str | None = None
        self._last_gpu_admit_at: float = 0.0
        self.min_gpu_switch_s = MIN_GPU_SWITCH_S

    def _slot_ok(self, loaded: list[dict], target: dict) -> bool:
        """GPU pool has room for target under MAX_GPU / exclusive rules."""
        others = others_loaded(loaded, target["model_id"])
        if target["tier"] == TIER_EXCLUSIVE:
            return len(others) == 0
        # Non-exclusive: at most max_gpu total including target once loaded.
        return len(others) < self.max_gpu

    def _mem_ok(self, target: dict) -> bool:
        avail = self.mem_available()
        if avail is None:
            return True  # degrade open on broken probe
        if avail < self.ram_floor_gb:
            return False
        return avail >= target["size_gb"] + self.headroom_gb

    def _gtt_ok(self, loaded: list[dict], target: dict) -> bool:
        """Hard-fail only when GTT is already above budget on an empty slot
        (stuck thrash). If other models remain, eviction handles it.
        """
        gtt = self.gtt_used()
        if gtt is None:
            return True
        others = others_loaded(loaded, target["model_id"])
        if others:
            return True
        return gtt <= self.gtt_budget_gb

    def _fits(self, loaded: list[dict], target: dict) -> bool:
        if free_gb(loaded, self.budget_gb) < target["size_gb"]:
            return False
        if not self._slot_ok(loaded, target):
            return False
        if not self._mem_ok(target):
            return False
        if not self._gtt_ok(loaded, target):
            return False
        return True

    def _swap_admits(self, loaded: list[dict], target: dict) -> bool:
        """Optional last resort — disabled by default. Never for exclusive
        or large models; never bypasses ledger or slot rules."""
        if not self.allow_swap_admit:
            return False
        if target["tier"] == TIER_EXCLUSIVE:
            return False
        if target["size_gb"] > self.swap_admit_max_size_gb:
            return False
        if not self._slot_ok(loaded, target):
            return False
        if free_gb(loaded, self.budget_gb) < target["size_gb"]:
            return False
        avail = self.mem_available()
        swap = self.swap_free()
        if avail is None or swap is None:
            return False
        return (
            avail >= self.ram_floor_gb
            and swap >= target["size_gb"] + self.headroom_gb
        )

    async def _try_comfy_reclaim(self) -> bool:
        if not COMFY_BASE or not COMFY_RECLAIM:
            return False
        try:
            if not await self.comfy_idle():
                return False
            return bool(await self.comfy_reclaim())
        except Exception:
            return False

    async def admit(self, alias: str, manifest: dict[str, dict]) -> None:
        """Return when `alias` may be forwarded; raise TimeoutError on hold expiry.

        PermissionError: alias not in GPU_ALLOW (service thrash guard).
        """
        target = manifest.get(alias)
        if target is None:
            return
        # Service thrash guard: only deliberate GPU aliases may load.
        if GPU_ALLOW and alias not in GPU_ALLOW:
            raise PermissionError(
                f"SMO: GPU model {alias!r} is not in allowlist "
                f"{sorted(GPU_ALLOW)}; background services must use "
                f"resident-small (NPU). Set AIPC_SCHED_GPU_ALLOW to expand."
            )
        health = await self.fetch_health()
        if health is None:
            return  # degrade open
        loaded = gpu_loaded(health, manifest)
        if any(m["model_id"] == target["model_id"] for m in loaded):
            # Already loaded: serve unless exclusive isolation is broken.
            if not (
                target["tier"] == TIER_EXCLUSIVE
                and others_loaded(loaded, target["model_id"])
            ):
                return
        async with self.lock:
            self._comfy_reclaimed = False
            deadline = self.clock() + self.hold_timeout_s
            while True:
                health = await self.fetch_health()
                if health is None:
                    return
                loaded = gpu_loaded(health, manifest)
                already = any(m["model_id"] == target["model_id"] for m in loaded)
                if already and self._slot_ok(loaded, target):
                    break
                # Anti-storm: refuse rapid switches between different GPU models
                # (voice+hermes+agent racing). Exclusive bypasses.
                if (
                    not already
                    and target["tier"] != TIER_EXCLUSIVE
                    and alias not in WORKHORSE
                    and self.min_gpu_switch_s > 0
                    and self._last_gpu_alias
                    and self._last_gpu_alias != alias
                    and (self.clock() - self._last_gpu_admit_at) < self.min_gpu_switch_s
                ):
                    raise TimeoutError(
                        f"SMO: GPU switch rate-limit "
                        f"({self._last_gpu_alias!r} -> {alias!r} within "
                        f"{self.min_gpu_switch_s:.0f}s); retry later or use "
                        f"resident-small"
                    )
                if not already and self._fits(loaded, target):
                    print(
                        f"[smo] admit {alias} size={target['size_gb']}Gi "
                        f"tier={target['tier']} avail={self.mem_available()} "
                        f"gtt={self.gtt_used()} loaded={[m['model_id'] for m in loaded]}",
                        flush=True,
                    )
                    break
                victim = pick_victim(
                    loaded, target, self.admitted_at, self.clock(), self.cooldown_s
                )
                if victim is not None:
                    print(f"[smo] unload {victim} for {alias}", flush=True)
                    await self.post_unload(victim)
                elif not self._comfy_reclaimed and await self._try_comfy_reclaim():
                    self._comfy_reclaimed = True
                    print(
                        f"[smo] reclaimed idle ComfyUI cache before admitting {alias}",
                        flush=True,
                    )
                    await self.sleeper(self.poll_s)
                elif self._swap_admits(loaded, target) and not already:
                    print(f"[smo] swap-admit {alias} (legacy path)", flush=True)
                    break
                else:
                    await self.sleeper(self.poll_s)
                if self.clock() > deadline:
                    raise TimeoutError(
                        f"SMO: cannot fit {alias} ({target['size_gb']}GB) "
                        f"budget={self.budget_gb}GB headroom={self.headroom_gb}GB "
                        f"ram_floor={self.ram_floor_gb}GB max_gpu={self.max_gpu} "
                        f"gtt_budget={self.gtt_budget_gb}GB "
                        f"loaded={[m['model_id'] for m in loaded]}"
                    )
            now = self.clock()
            self.admitted_at[target["model_id"]] = now
            self._last_gpu_alias = alias
            self._last_gpu_admit_at = now


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
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post(
                f"{LEMONADE_BASE}/api/v0/unload",
                json={"model_name": model_id},
            )
    except Exception:
        pass


async def _http_comfy_idle() -> bool:
    if not COMFY_BASE:
        return False
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{COMFY_BASE}/queue")
            if resp.status_code != 200:
                return False
            data = resp.json()
            return not data.get("queue_running") and not data.get("queue_pending")
    except Exception:
        return False


async def _http_comfy_reclaim() -> bool:
    if not COMFY_BASE:
        return False
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{COMFY_BASE}/free",
                json={"unload_models": True, "free_memory": True},
            )
            return resp.status_code == 200
    except Exception:
        return False


try:
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:
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
        except PermissionError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail=str(exc))
        except TimeoutError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail=str(exc))
        return data


scheduler = MemoryScheduler()


def self_test() -> None:
    # Self-test uses many aliases; clear allowlist for core cases then
    # re-enable for the allowlist-specific check at the end.
    global GPU_ALLOW
    GPU_ALLOW = set()  # allow all during unit tests
    manifest = parse_manifest({"models": [
        {"alias": "coder-122b", "backend": "lemonade",
         "model_id": "Q122", "size_gb": 59.2, "tier": "exclusive"},
        {"alias": "coder-agentic", "backend": "lemonade",
         "model_id": "Q36", "size_gb": 24.2, "tier": "floating"},
        {"alias": "assistant-gemma", "backend": "lemonade",
         "model_id": "G26", "size_gb": 15.6, "tier": "floating"},
        {"alias": "qwythos-9b", "backend": "lemonade",
         "model_id": "QW9", "size_gb": 5.6, "tier": "floating"},
        {"alias": "ornith-35b", "backend": "lemonade",
         "model_id": "ORN", "size_gb": 22.5, "tier": "floating"},
        {"alias": "resident-small", "backend": "lemonade",
         "model_id": "FLM", "size_gb": 9.6, "pool": "npu"},
        {"alias": "main-cloud", "backend": "anthropic",
         "model_id": "claude", "size_gb": "cloud"},
    ]})
    assert set(manifest) == {
        "coder-122b", "coder-agentic", "assistant-gemma",
        "qwythos-9b", "ornith-35b",
    }
    assert manifest["ornith-35b"]["tier"] == "floating"
    assert manifest["coder-122b"]["tier"] == "exclusive"

    def health_for(ids, in_use=()):
        return {"all_models_loaded": [
            {"model_name": i, "loaded": True, "last_use": n * 1000,
             "status": "in_use" if i in in_use else "idle"}
            for n, i in enumerate(ids)
        ]}

    # Exclusive evicts floating oldest last_use first (enumerate order).
    loaded = gpu_loaded(health_for(["Q36", "ORN", "G26"]), manifest)
    assert pick_victim(loaded, manifest["coder-122b"], {}, now=0.0) == "Q36"
    # Second pass.
    loaded = gpu_loaded(health_for(["ORN", "G26"]), manifest)
    assert pick_victim(loaded, manifest["coder-122b"], {}, now=0.0) == "ORN"
    # Floating can evict other floating (single-slot).
    loaded = gpu_loaded(health_for(["Q36"]), manifest)
    assert pick_victim(loaded, manifest["ornith-35b"], {}, now=0.0) == "Q36"
    # In-use exclusive not a victim for agent.
    loaded = gpu_loaded(health_for(["Q122"], in_use={"Q122"}), manifest)
    assert pick_victim(loaded, manifest["coder-agentic"], {}, now=0.0) is None
    # Cooldown blocks non-exclusive eviction of recent admit.
    loaded = gpu_loaded(health_for(["ORN", "QW9"]), manifest)
    recent = {"ORN": 100.0}
    assert pick_victim(loaded, manifest["qwythos-9b"], recent, now=150.0) is None
    assert pick_victim(loaded, manifest["coder-122b"], recent, now=150.0) == "ORN"

    async def run_async_cases():
        # 122B: must clear ALL others (single exclusive slot).
        state = {"loaded": ["Q36", "ORN", "G26", "QW9"], "unloads": []}

        async def fake_health():
            return health_for(state["loaded"])

        async def fake_unload(model_id):
            state["unloads"].append(model_id)
            state["loaded"].remove(model_id)

        core = _SchedulerCore(
            fake_health, fake_unload, budget_gb=80,
            hold_timeout_s=10, poll_s=0,
            mem_available=lambda: 999.0, gtt_used=lambda: 5.0,
            allow_swap_admit=False,
        )
        await core.admit("coder-122b", manifest)
        assert set(state["unloads"]) == {"ORN", "Q36", "G26", "QW9"}, state["unloads"]
        assert state["loaded"] == []

        # Fast path: already alone.
        state2 = {"loaded": ["Q122"], "unloads": []}

        async def health2():
            return health_for(state2["loaded"])

        async def unload2(model_id):
            state2["unloads"].append(model_id)

        core2 = _SchedulerCore(
            health2, unload2, budget_gb=80,
            mem_available=lambda: 999.0, gtt_used=lambda: 40.0,
            allow_swap_admit=False,
        )
        await core2.admit("coder-122b", manifest)
        assert state2["unloads"] == []

        # Single-slot: agentic request evicts ornith.
        state5 = {"loaded": ["ORN"], "unloads": []}

        async def health5():
            return health_for(state5["loaded"])

        async def unload5(model_id):
            state5["unloads"].append(model_id)
            state5["loaded"].remove(model_id)

        core5 = _SchedulerCore(
            health5, unload5, budget_gb=80,
            hold_timeout_s=10, poll_s=0,
            mem_available=lambda: 50.0, gtt_used=lambda: 20.0,
            allow_swap_admit=False,
        )
        await core5.admit("coder-agentic", manifest)
        assert state5["unloads"] == ["ORN"], state5["unloads"]

        # Hold: in-use exclusive blocks agent.
        state3 = {"loaded": ["Q122"], "unloads": []}

        async def health3():
            return health_for(state3["loaded"], in_use={"Q122"})

        async def unload3(model_id):
            state3["unloads"].append(model_id)

        clock = {"t": 0.0}

        async def instant_sleep(_s):
            clock["t"] += 5.0

        core3 = _SchedulerCore(
            health3, unload3, budget_gb=80,
            hold_timeout_s=20, poll_s=0,
            clock=lambda: clock["t"], sleeper=instant_sleep,
            mem_available=lambda: 999.0, gtt_used=lambda: 40.0,
            allow_swap_admit=False,
        )
        try:
            await core3.admit("coder-agentic", manifest)
        except TimeoutError:
            pass
        else:
            raise AssertionError("expected hold timeout against in-use exclusive")
        assert state3["unloads"] == []

        # Degrade open: health unreachable.
        async def health_none():
            return None

        core4 = _SchedulerCore(health_none, unload3, budget_gb=80)
        await core4.admit("coder-122b", manifest)

        # Unknown alias (cloud) passes.
        await core2.admit("main-cloud", manifest)

        # Real-memory floor: too little RAM, nothing loaded -> timeout.
        clock6 = {"t": 0.0}

        async def sleep6(_s):
            clock6["t"] += 5.0

        async def health_empty():
            return health_for([])

        core6 = _SchedulerCore(
            health_empty, unload3, budget_gb=80,
            hold_timeout_s=20, poll_s=0,
            clock=lambda: clock6["t"], sleeper=sleep6,
            mem_available=lambda: 8.0, gtt_used=lambda: 1.0,
            ram_floor_gb=12.0, allow_swap_admit=False,
        )
        try:
            await core6.admit("qwythos-9b", manifest)
        except TimeoutError:
            pass
        else:
            raise AssertionError("expected real-memory hold timeout")

        # Swap-admit OFF: even with huge swap, short MemAvailable holds.
        clock8 = {"t": 0.0}

        async def sleep8(_s):
            clock8["t"] += 5.0

        core8 = _SchedulerCore(
            health_empty, unload3, budget_gb=80,
            hold_timeout_s=20, poll_s=0,
            clock=lambda: clock8["t"], sleeper=sleep8,
            mem_available=lambda: 8.0, swap_free=lambda: 60.0,
            gtt_used=lambda: 1.0, ram_floor_gb=12.0,
            allow_swap_admit=False,
        )
        try:
            await core8.admit("qwythos-9b", manifest)
        except TimeoutError:
            pass
        else:
            raise AssertionError("swap admit must be off by default")

        # Swap-admit ON only for tiny models: still requires slot ok.
        core8b = _SchedulerCore(
            health_empty, unload3, budget_gb=80,
            hold_timeout_s=10, poll_s=0,
            mem_available=lambda: 13.0, swap_free=lambda: 60.0,
            gtt_used=lambda: 1.0, ram_floor_gb=12.0,
            allow_swap_admit=True, swap_admit_max_size_gb=8,
            headroom_gb=4,
        )
        await core8b.admit("qwythos-9b", manifest)

        # Exclusive never swap-admits.
        clock9 = {"t": 0.0}

        async def sleep9(_s):
            clock9["t"] += 5.0

        core9 = _SchedulerCore(
            health_empty, unload3, budget_gb=80,
            hold_timeout_s=20, poll_s=0,
            clock=lambda: clock9["t"], sleeper=sleep9,
            mem_available=lambda: 13.0, swap_free=lambda: 200.0,
            gtt_used=lambda: 1.0, ram_floor_gb=12.0,
            allow_swap_admit=True, swap_admit_max_size_gb=100,
            headroom_gb=4,
        )
        # 122B size 59.2 + headroom 4 needs avail>=63.2; with 13 fails mem_ok
        # and swap path is blocked for exclusive.
        try:
            await core9.admit("coder-122b", manifest)
        except TimeoutError:
            pass
        else:
            raise AssertionError("exclusive must not swap-admit")

        # Broken meminfo degrades to ledger+slot only.
        core7 = _SchedulerCore(
            health_empty, unload3, budget_gb=80,
            mem_available=lambda: None, gtt_used=lambda: None,
            allow_swap_admit=False,
        )
        await core7.admit("qwythos-9b", manifest)

        # Comfy reclaim once then hold (insufficient memory).
        global COMFY_BASE
        orig_comfy_base = COMFY_BASE
        COMFY_BASE = "http://127.0.0.1:8188"
        clock12 = {"t": 0.0}

        async def sleep12(_s):
            clock12["t"] += 5.0

        comfy_calls12 = {"reclaim": 0}

        async def comfy_idle_true12():
            return True

        async def comfy_reclaim_track12():
            comfy_calls12["reclaim"] += 1
            return True

        core12 = _SchedulerCore(
            health_empty, unload3, budget_gb=80,
            hold_timeout_s=20, poll_s=0,
            clock=lambda: clock12["t"], sleeper=sleep12,
            mem_available=lambda: 5.0, swap_free=lambda: 1.0,
            gtt_used=lambda: 1.0, ram_floor_gb=12.0,
            allow_swap_admit=False,
            comfy_idle=comfy_idle_true12,
            comfy_reclaim=comfy_reclaim_track12,
        )
        try:
            await core12.admit("qwythos-9b", manifest)
        except TimeoutError:
            pass
        else:
            raise AssertionError("expected hold timeout")
        assert comfy_calls12["reclaim"] == 1, comfy_calls12

        # Concurrent: A holds lock timing out; B fast-path on already loaded.
        clock14 = {"t": 0.0}

        async def sleep14(_s):
            clock14["t"] += 5.0
            await asyncio.sleep(0)

        comfy_calls14 = {"reclaim": 0}

        async def health14():
            # QW9 in_use: A cannot steal it; B still fast-paths as already loaded.
            return health_for(["QW9"], in_use={"QW9"})

        async def unload14(model_id):
            raise AssertionError("no eviction expected in concurrent case")

        async def comfy_reclaim_track14():
            comfy_calls14["reclaim"] += 1
            return True

        async def comfy_idle_true14():
            return True

        core14 = _SchedulerCore(
            health14, unload14, budget_gb=80,
            hold_timeout_s=20, poll_s=0,
            clock=lambda: clock14["t"], sleeper=sleep14,
            mem_available=lambda: 8.0, swap_free=lambda: 1.0,
            gtt_used=lambda: 50.0, ram_floor_gb=12.0,
            allow_swap_admit=False,
            comfy_idle=comfy_idle_true14,
            comfy_reclaim=comfy_reclaim_track14,
        )

        async def admit_a():
            try:
                await core14.admit("assistant-gemma", manifest)
            except TimeoutError:
                pass
            else:
                raise AssertionError("expected A hold timeout")

        await asyncio.gather(admit_a(), core14.admit("qwythos-9b", manifest))
        assert comfy_calls14["reclaim"] == 1, comfy_calls14

        COMFY_BASE = orig_comfy_base

    asyncio.run(run_async_cases())

    # Allowlist: assistant-gemma blocked by default GPU_ALLOW.
    prev_allow = GPU_ALLOW
    GPU_ALLOW = {"coder-agentic", "coder-122b"}

    async def allow_cases():
        async def health_empty():
            return health_for([])

        async def unload_noop(_m):
            pass

        core = _SchedulerCore(
            health_empty, unload_noop, budget_gb=80,
            mem_available=lambda: 999.0, gtt_used=lambda: 1.0,
            allow_swap_admit=False,
        )
        try:
            await core.admit("assistant-gemma", manifest)
        except PermissionError:
            pass
        else:
            raise AssertionError("expected PermissionError for blocked alias")
        await core.admit("coder-agentic", manifest)

    asyncio.run(allow_cases())
    GPU_ALLOW = prev_allow
    print("scheduler_hook self-test passed (SMO)")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        print("usage: scheduler_hook.py --self-test", file=sys.stderr)
        sys.exit(2)
