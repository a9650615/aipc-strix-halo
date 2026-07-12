#!/usr/bin/env python3
"""Release idle Lemonade models; re-warm the resident agent set (0006/0012)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_MANIFEST = Path("/etc/aipc/models/models.yaml")
DEFAULT_UNLOAD_PATH = "/api/v0/unload"
DEFAULT_LOAD_PATH = "/api/v0/load"
# Same budget the 0012 gateway scheduler uses — re-warm must never evict.
BUDGET_GB = float(os.environ.get("AIPC_SCHED_BUDGET_GB", "96"))


def _load_manifest(path: Path) -> list[dict]:
    """All Lemonade GPU entries (pool != npu), with idle/tier/size fields."""
    data = yaml.safe_load(path.read_text())
    models = data.get("models", []) if isinstance(data, dict) else []
    result: list[dict] = []
    for entry in models:
        if not isinstance(entry, dict) or entry.get("backend") != "lemonade":
            continue
        if entry.get("pool") == "npu":
            continue
        model_id = entry.get("model_id")
        if not model_id:
            continue
        idle = entry.get("idle_unload_after_s")
        if idle is not None and not isinstance(idle, (int, float)):
            name = entry.get("alias", model_id)
            raise ValueError(f"{name}: idle_unload_after_s must be numeric")
        size = entry.get("size_gb")
        result.append({
            "alias": entry.get("alias", model_id),
            "model_id": model_id,
            "idle_unload_after_s": float(idle) if idle is not None else None,
            "tier": str(entry.get("tier", "floating")),
            "size_gb": float(size) if isinstance(size, (int, float)) else None,
        })
    return result


def _load_health(base_url: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{base_url}/api/v0/health", timeout=5) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _loaded_models(health: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    models = health.get("all_models_loaded", [])
    if not isinstance(models, list):
        return result
    for entry in models:
        if not isinstance(entry, dict) or not entry.get("loaded"):
            continue
        key = entry.get("model_name") or entry.get("name")
        if isinstance(key, str) and key:
            result[key] = entry
    return result


def _last_use_age_seconds(entry: dict, now: float) -> float | None:
    last_use = entry.get("last_use")
    if not isinstance(last_use, (int, float)):
        return None
    return max(0.0, now - float(last_use) / 1000.0)


def _expired_candidates(manifest: list[dict], health: dict, now: float) -> list[dict]:
    loaded = _loaded_models(health)
    candidates: list[dict] = []
    for spec in manifest:
        idle_after = spec.get("idle_unload_after_s")
        if not isinstance(idle_after, (int, float)):
            continue
        live = loaded.get(spec["model_id"])
        if not live or live.get("pinned") or live.get("status") == "in_use":
            continue
        age = _last_use_age_seconds(live, now)
        if age is None or age < float(idle_after):
            continue
        candidates.append({
            "alias": spec["alias"],
            "model_id": spec["model_id"],
            "idle_unload_after_s": float(idle_after),
            "idle_age_s": age,
        })
    candidates.sort(key=lambda item: item["idle_age_s"], reverse=True)
    return candidates


def _unload(base_url: str, model_id: str) -> None:
    payload = json.dumps({"model_name": model_id}).encode()
    req = urllib.request.Request(
        f"{base_url}{DEFAULT_UNLOAD_PATH}",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _load_model(base_url: str, model_id: str) -> None:
    payload = json.dumps({"model_name": model_id}).encode()
    req = urllib.request.Request(
        f"{base_url}{DEFAULT_LOAD_PATH}",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    # A 20+GB load takes a while; the daemon runs from a timer so blocking is fine.
    with urllib.request.urlopen(req, timeout=600) as resp:
        resp.read()


def _rewarm_candidate(manifest: list[dict], health: dict, budget_gb: float = BUDGET_GB) -> dict | None:
    """One resident-tier model to reload, or None (0012 resident restore).

    Only when no exclusive-tier model is loaded, and only if the candidate
    fits the remaining budget without evicting anything — smallest first so
    the set converges over successive cycles.
    """
    loaded = _loaded_models(health)
    by_model_id = {spec["model_id"]: spec for spec in manifest}
    for model_id in loaded:
        spec = by_model_id.get(model_id)
        if spec and spec["tier"] == "exclusive":
            return None
    used = sum(
        by_model_id[mid]["size_gb"] or 0.0
        for mid in loaded
        if mid in by_model_id
    )
    missing = sorted(
        (
            spec for spec in manifest
            if spec["tier"] == "resident"
            and spec["model_id"] not in loaded
            and spec["size_gb"] is not None
        ),
        key=lambda spec: spec["size_gb"],
    )
    for spec in missing:
        if used + spec["size_gb"] <= budget_gb:
            return spec
    return None


def run(base_url: str, manifest_path: Path) -> int:
    try:
        manifest = _load_manifest(manifest_path)
    except FileNotFoundError:
        print(f"lemonade-idle-release: manifest missing: {manifest_path}", file=sys.stderr)
        return 0
    except Exception as exc:
        print(f"lemonade-idle-release: failed to read manifest: {exc}", file=sys.stderr)
        return 1

    if not manifest:
        print("lemonade-idle-release: no lemonade GPU models declared", file=sys.stderr)
        return 0

    health = _load_health(base_url)
    if health is None:
        print("lemonade-idle-release: Lemonade health unreachable", file=sys.stderr)
        return 0

    candidates = _expired_candidates(manifest, health, time.monotonic())
    if candidates:
        target = candidates[0]
        try:
            _unload(base_url, target["model_id"])
        except Exception as exc:
            print(f"lemonade-idle-release: unload failed for {target['model_id']}: {exc}", file=sys.stderr)
            return 1
        print(
            f"lemonade-idle-release: unloaded {target['alias']} ({target['model_id']}) after "
            f"{int(target['idle_age_s'])}s idle",
            file=sys.stderr,
        )
        return 0

    rewarm = _rewarm_candidate(manifest, health)
    if rewarm is None:
        print("lemonade-idle-release: no expired idle models, resident set intact", file=sys.stderr)
        return 0
    try:
        _load_model(base_url, rewarm["model_id"])
    except Exception as exc:
        print(f"lemonade-idle-release: re-warm failed for {rewarm['model_id']}: {exc}", file=sys.stderr)
        return 1
    print(
        f"lemonade-idle-release: re-warmed resident {rewarm['alias']} ({rewarm['model_id']})",
        file=sys.stderr,
    )
    return 0


def self_test() -> None:
    now = 1_000.0
    model_id = "Gemma4-E2B-it-qat-UD-Q4_K_XL"
    manifest = [
        {"alias": "coder-compact", "model_id": model_id, "idle_unload_after_s": 300,
         "tier": "floating", "size_gb": 2.7},
        {"alias": "ornith-35b", "model_id": "Ornith-1.0-35B-MTP-APEX-I-Balanced",
         "idle_unload_after_s": None, "tier": "floating", "size_gb": 26.0},
    ]
    health = {"all_models_loaded": [
        {"model_name": model_id, "loaded": True, "pinned": False, "last_use": 650_000.0},
    ]}
    candidates = _expired_candidates(manifest, health, now)
    assert [candidate["model_id"] for candidate in candidates] == [model_id]
    assert int(candidates[0]["idle_age_s"]) == 350
    assert _last_use_age_seconds({"last_use": 990_000.0}, now) == 10.0
    health["all_models_loaded"][0].update(status="in_use", last_use=0.0)
    assert not _expired_candidates(manifest, health, now)
    assert _last_use_age_seconds({"last_use": "bad"}, now) is None

    # 0012 resident re-warm: missing residents reload smallest-first...
    sched_manifest = [
        {"alias": "coder-122b", "model_id": "Q122", "idle_unload_after_s": 600,
         "tier": "exclusive", "size_gb": 59.2},
        {"alias": "coder-agentic", "model_id": "Q36", "idle_unload_after_s": None,
         "tier": "resident", "size_gb": 21.8},
        {"alias": "qwythos-9b", "model_id": "QW9", "idle_unload_after_s": None,
         "tier": "resident", "size_gb": 5.6},
    ]
    empty = {"all_models_loaded": []}
    assert _rewarm_candidate(sched_manifest, empty, budget_gb=96)["alias"] == "qwythos-9b"
    # ...never while an exclusive model is loaded...
    excl = {"all_models_loaded": [{"model_name": "Q122", "loaded": True}]}
    assert _rewarm_candidate(sched_manifest, excl, budget_gb=96) is None
    # ...and never beyond the budget (no eviction from the re-warm path).
    assert _rewarm_candidate(sched_manifest, empty, budget_gb=5) is None
    # Fully warm set -> nothing to do.
    warm = {"all_models_loaded": [
        {"model_name": "Q36", "loaded": True}, {"model_name": "QW9", "loaded": True},
    ]}
    assert _rewarm_candidate(sched_manifest, warm, budget_gb=96) is None
    print("self-test passed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    return run(args.base_url, Path(args.manifest))


if __name__ == "__main__":
    raise SystemExit(main())
