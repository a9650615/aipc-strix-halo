"""LLM scheduling / guard observability for Control Center Models page.

Read-only composition of:
  * SMO (scheduler_hook) policy knobs
  * host capacity gates (MemAvailable, GTT)
  * Lemonade loaded models + max_models
  * models.yaml idle_unload / tier policy
  * idle-release keep-warm decision (simulated, same rules as lemonade-idle-release)
  * OOM-guard event ring buffer

Never triggers load/unload. Short timeouts only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from aipc_portal.dashboard import (
    PROBE_TIMEOUT_S,
    _bytes_to_gib,
    _gtt_info,
    _http_json,
    _meminfo,
    _read_text,
)
from aipc_portal.http_cache import TtlCache

MANIFEST_CANDIDATES = (
    Path("/etc/aipc/models/models.yaml"),
    Path("/var/lib/aipc/models/models.yaml"),
)
LEMONADE_HEALTH = "http://127.0.0.1:8001/api/v0/health"
OOM_EVENTS = Path("/var/lib/aipc-oom-guard/events.jsonl")
OOM_DISABLED = Path("/etc/aipc/oom-guard.disabled")
# Keep last successful lemonade payload so short probe timeouts don't flash empty UI.
_LEMONADE_STALE_S = 90.0
_lemonade_last_good: dict[str, Any] | None = None
_lemonade_last_good_at = 0.0

# Defaults mirror scheduler_hook.py / idle-release (live unit may override).
DEFAULT_POLICY: dict[str, Any] = {
    "max_gpu_loaded": 2,
    "budget_gb": 80.0,
    "headroom_gb": 12.0,
    "ram_floor_gb": 12.0,
    "gtt_budget_gb": 70.0,
    "large_gb": 12.0,
    "allow_swap_admit": False,
    "min_gpu_switch_s": 0.0,
    "workhorse": ["coder-agentic"],
    "keep_warm_mem_floor_gb": 25.0,
    "load_timeout_s": 150.0,
    "cooldown_s": 120.0,
}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _unit_env(unit: str) -> dict[str, str]:
    """Best-effort Environment= from a systemd unit (portal often runs as root)."""
    try:
        proc = subprocess.run(
            ["systemctl", "show", unit, "-p", "Environment", "--value"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    out: dict[str, str] = {}
    for token in (proc.stdout or "").split():
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        out[k] = v
    return out


def policy_snapshot() -> dict[str, Any]:
    unit = _unit_env("litellm.service")
    idle_unit = _unit_env("aipc-lemonade-idle-release.service")

    def g(key: str, default: str = "") -> str:
        return unit.get(key) or os.environ.get(key) or default

    workhorse_raw = g("AIPC_SCHED_WORKHORSE", "coder-agentic")
    allow_raw = g("AIPC_SCHED_GPU_ALLOW", "")
    keep_warm = idle_unit.get("AIPC_IDLE_KEEP_WARM_MEM_FLOOR_GB") or os.environ.get(
        "AIPC_IDLE_KEEP_WARM_MEM_FLOOR_GB", str(DEFAULT_POLICY["keep_warm_mem_floor_gb"])
    )
    try:
        keep_warm_f = float(keep_warm)
    except ValueError:
        keep_warm_f = float(DEFAULT_POLICY["keep_warm_mem_floor_gb"])

    swap = g("AIPC_SCHED_ALLOW_SWAP_ADMIT", "0")
    policy = {
        "max_gpu_loaded": _env_int("AIPC_SCHED_MAX_GPU", int(g("AIPC_SCHED_MAX_GPU") or DEFAULT_POLICY["max_gpu_loaded"])),
        "budget_gb": float(g("AIPC_SCHED_BUDGET_GB") or DEFAULT_POLICY["budget_gb"]),
        "headroom_gb": float(g("AIPC_SCHED_HEADROOM_GB") or DEFAULT_POLICY["headroom_gb"]),
        "ram_floor_gb": float(g("AIPC_SCHED_RAM_FLOOR_GB") or DEFAULT_POLICY["ram_floor_gb"]),
        "gtt_budget_gb": float(g("AIPC_SCHED_GTT_BUDGET_GB") or DEFAULT_POLICY["gtt_budget_gb"]),
        "large_gb": float(g("AIPC_SCHED_LARGE_GB") or DEFAULT_POLICY["large_gb"]),
        "allow_swap_admit": swap not in ("0", "", "false", "False"),
        "min_gpu_switch_s": float(g("AIPC_SCHED_MIN_GPU_SWITCH_S") or DEFAULT_POLICY["min_gpu_switch_s"]),
        "workhorse": [a.strip() for a in workhorse_raw.split(",") if a.strip()],
        "gpu_allowlist": [a.strip() for a in allow_raw.split(",") if a.strip()],
        "keep_warm_mem_floor_gb": keep_warm_f,
        "load_timeout_s": float(g("AIPC_SCHED_LOAD_TIMEOUT_S") or DEFAULT_POLICY["load_timeout_s"]),
        "cooldown_s": float(g("AIPC_SCHED_COOLDOWN_S") or DEFAULT_POLICY["cooldown_s"]),
        "owner": "SMO scheduler_hook (LiteLLM callback)",
        "idle_owner": "lemonade-idle-release timer",
        "oom_owner": "aipc-oom-guard",
    }
    # Prefer unit env over process env for MAX_GPU when present
    if "AIPC_SCHED_MAX_GPU" in unit:
        try:
            policy["max_gpu_loaded"] = int(unit["AIPC_SCHED_MAX_GPU"])
        except ValueError:
            pass
    return policy


def _parse_yaml_models(text: str) -> list[dict[str, Any]]:
    """Minimal models.yaml slice — enough for alias/tier/idle/size/pool/backend."""
    # Prefer PyYAML if available
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        rows = data.get("models") if isinstance(data, dict) else None
        if isinstance(rows, list):
            out = []
            for e in rows:
                if not isinstance(e, dict):
                    continue
                out.append(
                    {
                        "alias": e.get("alias"),
                        "model_id": e.get("model_id"),
                        "backend": e.get("backend"),
                        "pool": e.get("pool"),
                        "tier": e.get("tier") or "floating",
                        "size_gb": e.get("size_gb"),
                        "idle_unload_after_s": e.get("idle_unload_after_s"),
                    }
                )
            return out
    except Exception:
        pass
    return []


def load_manifest(path: Path | None = None) -> tuple[list[dict[str, Any]], str | None]:
    candidates = [path] if path else list(MANIFEST_CANDIDATES)
    for p in candidates:
        if p is None or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        rows = _parse_yaml_models(text)
        if rows:
            return rows, str(p)
    return [], None


def _match_manifest(live_name: str, manifest: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in manifest:
        mid = str(row.get("model_id") or "")
        alias = str(row.get("alias") or "")
        if live_name == mid or live_name == alias:
            return row
        if mid and (mid in live_name or live_name in mid):
            return row
        if alias and alias in live_name:
            return row
    return None


def _last_use_age_s(entry: dict[str, Any], now_mono: float) -> float | None:
    last_use = entry.get("last_use")
    if not isinstance(last_use, (int, float)):
        return None
    # Lemonade: last_use is ms of a monotonic clock (see idle-release self-test).
    return max(0.0, now_mono - float(last_use) / 1000.0)


def _short(name: str, n: int = 42) -> str:
    s = str(name or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def capacity_snapshot(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or policy_snapshot()
    mem = _meminfo()
    gtt = _gtt_info()
    avail = mem.get("mem_available_gb")
    total = mem.get("mem_total_gb")
    gtt_used = gtt.get("gtt_used_gb")
    gtt_total = gtt.get("gtt_total_gb")
    floor = float(policy["ram_floor_gb"])
    headroom = float(policy["headroom_gb"])
    gtt_budget = float(policy["gtt_budget_gb"])
    keep_warm = float(policy["keep_warm_mem_floor_gb"])

    gates: list[dict[str, Any]] = []
    if avail is not None:
        gates.append(
            {
                "id": "ram_floor",
                "label": "RAM floor",
                "ok": avail >= floor,
                "detail": f"MemAvailable {avail:.1f}G ≥ floor {floor:.0f}G",
                "value": avail,
                "limit": floor,
            }
        )
        gates.append(
            {
                "id": "keep_warm",
                "label": "Keep-warm (idle unload)",
                "ok": avail >= keep_warm,
                "detail": (
                    f"MemAvailable {avail:.1f}G ≥ {keep_warm:.0f}G → skip idle unload"
                    if avail >= keep_warm
                    else f"MemAvailable {avail:.1f}G < {keep_warm:.0f}G → idle unload armed"
                ),
                "value": avail,
                "limit": keep_warm,
                "armed": avail < keep_warm,
            }
        )
    if gtt_used is not None:
        gates.append(
            {
                "id": "gtt_budget",
                "label": "GTT budget",
                "ok": gtt_used < gtt_budget,
                "detail": f"GTT used {gtt_used:.1f}G / budget {gtt_budget:.0f}G",
                "value": gtt_used,
                "limit": gtt_budget,
            }
        )
    gates.append(
        {
            "id": "swap_admit",
            "label": "Swap admit",
            "ok": not policy["allow_swap_admit"],
            "detail": "disabled (thrash protection)" if not policy["allow_swap_admit"] else "ENABLED",
            "value": policy["allow_swap_admit"],
            "limit": False,
        }
    )

    return {
        "mem_available_gb": avail,
        "mem_total_gb": total,
        "gtt_used_gb": gtt_used,
        "gtt_total_gb": gtt_total,
        "headroom_gb": headroom,
        "gates": gates,
        "summary": (
            f"{avail:.0f}/{total:.0f}G free · GTT {gtt_used:.1f}G"
            if avail is not None and total is not None and gtt_used is not None
            else "capacity partial"
        ),
    }


def lemonade_live(*, timeout: float = PROBE_TIMEOUT_S) -> dict[str, Any]:
    global _lemonade_last_good, _lemonade_last_good_at
    data = _http_json(LEMONADE_HEALTH, timeout=timeout)
    if not data:
        # Probe miss: serve last-good for a short window (stops empty/full flicker).
        if (
            _lemonade_last_good is not None
            and (time.monotonic() - _lemonade_last_good_at) < _LEMONADE_STALE_S
        ):
            stale = dict(_lemonade_last_good)
            stale["availability"] = "stale"
            stale["stale"] = True
            return stale
        return {
            "availability": "unavailable",
            "models": [],
            "max_models": {},
            "pinned_models": {},
            "stale": False,
        }
    rows = data.get("all_models_loaded") or []
    models = [r for r in rows if isinstance(r, dict) and r.get("loaded")]
    result = {
        "availability": "available",
        "models": models,
        "max_models": data.get("max_models") or {},
        "pinned_models": data.get("pinned_models") or {},
        "model_loaded": data.get("model_loaded"),
        "stale": False,
    }
    _lemonade_last_good = result
    _lemonade_last_good_at = time.monotonic()
    return result


def evaluate_loaded(
    live: dict[str, Any],
    manifest: list[dict[str, Any]],
    policy: dict[str, Any],
    capacity: dict[str, Any],
) -> list[dict[str, Any]]:
    now_mono = time.monotonic()
    avail = capacity.get("mem_available_gb")
    keep_warm = float(policy["keep_warm_mem_floor_gb"])
    keep_warm_active = avail is not None and float(avail) >= keep_warm
    out: list[dict[str, Any]] = []
    for row in live.get("models") or []:
        name = str(row.get("model_name") or row.get("name") or "unknown")
        spec = _match_manifest(name, manifest)
        age = _last_use_age_s(row, now_mono)
        idle_after = spec.get("idle_unload_after_s") if spec else None
        try:
            idle_after_f = float(idle_after) if idle_after is not None else None
        except (TypeError, ValueError):
            idle_after_f = None
        pinned = bool(row.get("pinned"))
        status = str(row.get("status") or "")
        device = str(row.get("device") or "")
        reasons: list[str] = []
        unloadable = False
        decision = "hold"

        if pinned:
            reasons.append("pinned — never idle-unloaded")
            decision = "protected"
        elif status == "in_use":
            reasons.append("status=in_use — idle-release skips")
            decision = "in_use"
        elif device == "npu" or "flm" in name.lower():
            reasons.append("NPU/FLM resident path (outside GPU pool idle list if pool=npu)")
            decision = "npu"
        elif keep_warm_active:
            reasons.append(
                f"keep-warm gate: MemAvailable {avail:.1f}G ≥ {keep_warm:.0f}G — skip all idle unload"
            )
            decision = "keep_warm"
        elif idle_after_f is None:
            reasons.append("no idle_unload_after_s in manifest")
            decision = "no_policy"
        elif age is None:
            reasons.append("last_use unknown")
            decision = "unknown_age"
        elif age < idle_after_f:
            left = idle_after_f - age
            reasons.append(f"idle {age:.0f}s < threshold {idle_after_f:.0f}s ({left:.0f}s left)")
            decision = "cooling"
        else:
            reasons.append(
                f"idle {age:.0f}s ≥ {idle_after_f:.0f}s AND MemAvailable < keep-warm → unload candidate"
            )
            decision = "unload_candidate"
            unloadable = True

        if device == "gpu" and not pinned:
            reasons.append(f"SMO GPU pool (max {policy['max_gpu_loaded']})")

        out.append(
            {
                "name": name,
                "name_short": _short(name),
                "alias": (spec or {}).get("alias"),
                "device": device or None,
                "recipe": row.get("recipe"),
                "status": status or None,
                "pinned": pinned,
                "backend_health": row.get("backend_health"),
                "ctx": (row.get("recipe_options") or {}).get("ctx_size")
                if isinstance(row.get("recipe_options"), dict)
                else row.get("max_context_window"),
                "idle_age_s": round(age, 1) if age is not None else None,
                "idle_unload_after_s": idle_after_f,
                "tier": (spec or {}).get("tier"),
                "size_gb": (spec or {}).get("size_gb"),
                "decision": decision,
                "unload_candidate": unloadable,
                "reasons": reasons,
            }
        )
    # Sort: unload candidates first, then GPU in_use, then rest
    order = {"unload_candidate": 0, "cooling": 1, "in_use": 2, "keep_warm": 3, "npu": 4}
    out.sort(key=lambda r: (order.get(str(r["decision"]), 9), r["name"]))
    return out


def catalog_rows(manifest: list[dict[str, Any]], loaded_names: set[str]) -> list[dict[str, Any]]:
    rows = []
    for e in manifest:
        if e.get("backend") not in (None, "lemonade", "ollama") and e.get("size_gb") == "cloud":
            continue
        if e.get("size_gb") == "cloud":
            continue
        mid = str(e.get("model_id") or "")
        alias = str(e.get("alias") or mid)
        loaded = any(mid and mid in n or alias == n or alias in n for n in loaded_names)
        rows.append(
            {
                "alias": alias,
                "model_id": mid or None,
                "model_id_short": _short(mid, 36) if mid else None,
                "backend": e.get("backend"),
                "pool": e.get("pool") or ("npu" if e.get("pool") == "npu" else "gpu"),
                "tier": e.get("tier") or "floating",
                "size_gb": e.get("size_gb"),
                "idle_unload_after_s": e.get("idle_unload_after_s"),
                "loaded": loaded,
            }
        )
    # Prefer local lemonade first
    rows.sort(key=lambda r: (0 if r.get("backend") == "lemonade" else 1, str(r.get("alias"))))
    return rows


def idle_release_status(
    policy: dict[str, Any],
    capacity: dict[str, Any],
    evaluations: list[dict[str, Any]],
) -> dict[str, Any]:
    avail = capacity.get("mem_available_gb")
    floor = float(policy["keep_warm_mem_floor_gb"])
    candidates = [e for e in evaluations if e.get("unload_candidate")]
    if avail is not None and float(avail) >= floor:
        return {
            "state": "keep_warm",
            "summary": f"Keep-warm active — MemAvailable {float(avail):.1f}G ≥ {floor:.0f}G; idle unload skipped",
            "candidates": [],
            "next_action": "none",
        }
    if candidates:
        top = candidates[0]
        return {
            "state": "armed",
            "summary": f"Idle unload armed — next victim {top.get('alias') or top.get('name_short')}",
            "candidates": candidates,
            "next_action": "unload_on_timer",
        }
    return {
        "state": "idle_watch",
        "summary": "RAM below keep-warm floor but no expired idle models (in_use/pinned/cooling)",
        "candidates": [],
        "next_action": "wait",
    }


def _tail_jsonl(path: Path, limit: int = 40) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = path.read_bytes()
        if len(data) > 400_000:
            data = data[-400_000:]
        text = data.decode("utf-8", errors="replace")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows[-limit:]


def oom_guard_snapshot(limit: int = 30) -> dict[str, Any]:
    disabled = OOM_DISABLED.is_file()
    events = _tail_jsonl(OOM_EVENTS, limit=limit)
    # Compact for UI
    compact = []
    for e in reversed(events):
        compact.append(
            {
                "ts": e.get("ts"),
                "event": e.get("event") or e.get("action") or e.get("level"),
                "level": e.get("level"),
                "action": e.get("action"),
                "detail": e.get("target")
                or e.get("target_cgroup")
                or e.get("reason")
                or e.get("to")
                or e.get("result"),
                "mem": e.get("mem") or e.get("mem_before"),
                "dry_run": e.get("dry_run"),
            }
        )
    return {
        "disabled": disabled,
        "availability": "available" if events or OOM_EVENTS.is_file() else "unavailable",
        "events": compact[:limit],
        "path": str(OOM_EVENTS),
    }


def idle_journal_lines(limit: int = 12) -> list[str]:
    try:
        proc = subprocess.run(
            [
                "journalctl",
                "-u",
                "aipc-lemonade-idle-release.service",
                "-n",
                str(limit),
                "--no-pager",
                "-o",
                "cat",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    return lines[-limit:]


def _scheduling_snapshot_uncached() -> dict[str, Any]:
    policy = policy_snapshot()
    capacity = capacity_snapshot(policy)
    live = lemonade_live()
    manifest, manifest_path = load_manifest()
    evaluations = evaluate_loaded(live, manifest, policy, capacity)
    loaded_names = {str(e["name"]) for e in evaluations}
    catalog = catalog_rows(manifest, loaded_names)
    idle = idle_release_status(policy, capacity, evaluations)
    oom = oom_guard_snapshot()
    gpu_loaded = sum(1 for e in evaluations if e.get("device") == "gpu")
    npu_loaded = sum(1 for e in evaluations if e.get("device") == "npu" or e.get("decision") == "npu")
    max_llm = (live.get("max_models") or {}).get("llm")

    summary_parts = [
        capacity.get("summary") or "capacity n/a",
        f"{len(evaluations)} loaded",
        f"GPU {gpu_loaded}/{policy['max_gpu_loaded']}",
        idle.get("state") or "",
    ]
    if live.get("stale"):
        summary_parts.append("lemonade stale")
    return {
        "summary": " · ".join(p for p in summary_parts if p),
        "generated_at": time.time(),
        "policy": policy,
        "capacity": capacity,
        "lemonade": {
            "availability": live.get("availability"),
            "stale": bool(live.get("stale")),
            "max_models": live.get("max_models"),
            "gpu_loaded": gpu_loaded,
            "npu_loaded": npu_loaded,
            "max_llm": max_llm,
        },
        "loaded": evaluations,
        "catalog": catalog,
        "idle_release": idle,
        "idle_journal": idle_journal_lines(),
        "oom_guard": oom,
        "manifest_path": manifest_path,
        "legend": [
            {"id": "keep_warm", "label": "Keep-warm", "hint": "MemAvailable above floor → never idle-unload"},
            {"id": "in_use", "label": "In use", "hint": "status=in_use is never idle-unloaded"},
            {"id": "pinned", "label": "Pinned", "hint": "NPU resident / pinned flags"},
            {"id": "cooling", "label": "Cooling", "hint": "Idle age below idle_unload_after_s"},
            {"id": "unload_candidate", "label": "Unload candidate", "hint": "Would be unloaded on next armed timer tick"},
            {"id": "smo", "label": "SMO", "hint": "LiteLLM scheduler_hook admits/evicts GPU loads"},
            {"id": "oom", "label": "OOM guard", "hint": "SOFT unload / HARD restart under memory floor"},
        ],
    }


def scheduling_snapshot(*, use_cache: bool = True) -> dict[str, Any]:
    if not use_cache:
        return _scheduling_snapshot_uncached()
    value, _body, _etag = _SCHED_CACHE.get_or_build(_scheduling_snapshot_uncached)
    return value


def scheduling_snapshot_cached() -> tuple[dict[str, Any], bytes, str]:
    """Return (value, body, etag) for HTTP layer."""
    return _SCHED_CACHE.get_or_build(_scheduling_snapshot_uncached)

_SCHED_CACHE = TtlCache(ttl_s=3.0)
