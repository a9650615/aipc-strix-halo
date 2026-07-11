from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from aipc_portal.registry import ServiceStatus, load_automation, load_services, probe_all

DEVICE_STATE = Path("/run/aipc/command-center.json")
NPU_DEVICE = Path("/dev/accel/accel0")
TYPEC_ROOT = Path("/sys/class/typec")
LEMONADE_HEALTH = "http://127.0.0.1:8001/api/v0/health"
OLLAMA_MODELS = "http://127.0.0.1:11434/api/ps"
MODEL_MANIFEST = Path("/etc/aipc/models/models.yaml")
IDLE_RELEASE_TIMER = "aipc-lemonade-idle-release.timer"


def _systemctl_state(command: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", command, IDLE_RELEASE_TIMER],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def compact_idle_snapshot(
    models: list[dict[str, object]],
    *,
    manifest_path: Path = MODEL_MANIFEST,
    now: float | None = None,
    timer_enabled: str | None = None,
    timer_active: str | None = None,
) -> dict[str, object]:
    enabled = timer_enabled if timer_enabled is not None else _systemctl_state("is-enabled")
    active = timer_active if timer_active is not None else _systemctl_state("is-active")
    timer = "active" if enabled == "enabled" and active == "active" else (
        "inactive" if enabled == "enabled" else (
            "disabled" if enabled == "disabled" else "unknown"
        )
    )
    result: dict[str, object] = {
        "model": "coder-compact", "state": "unknown", "timer": timer,
        "timeout_s": None, "idle_s": None, "remaining_s": None,
    }
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        policy = next(
            row for row in manifest.get("models", [])
            if row.get("alias") == "coder-compact"
        )
        model_id = str(policy["model_id"])
        timeout = int(policy["idle_unload_after_s"])
    except (OSError, yaml.YAMLError, AttributeError, TypeError, ValueError, KeyError, StopIteration):
        return result
    result["timeout_s"] = timeout
    loaded = next(
        (row for row in models
         if row.get("backend") == "lemonade"
         and row.get("model_name") == model_id),
        None,
    )
    if loaded is None:
        result["state"] = "unloaded"
        return result
    if loaded.get("status") == "in_use":
        result["state"] = "in_use"
        return result
    last_use = loaded.get("last_use")
    if not isinstance(last_use, (int, float)):
        return result
    idle = max(0, int((time.monotonic() if now is None else now) - last_use / 1000))
    result.update(state="idle", idle_s=idle, remaining_s=max(0, timeout - idle))
    return result


def io_snapshot(root: Path = TYPEC_ROOT) -> dict[str, object]:
    ports: list[dict[str, str]] = []
    for port in sorted(root.glob("port*")) if root.is_dir() else []:
        try:
            role = (port / "data_role").read_text(encoding="utf-8").strip().lower()
        except OSError:
            role = ""
        ports.append({"id": port.name, "state": "connected" if role and role != "[none]" else "idle"})
    return {"availability": "available" if ports else "unavailable", "ports": ports}


def device_snapshot(path: Path = DEVICE_STATE) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        value: dict[str, object] = {"availability": "unavailable", "detail": "device state file not found"}
    except (OSError, ValueError):
        value = {"availability": "unavailable", "detail": "device state unreadable"}
    if not isinstance(value, dict):
        value = {"availability": "unavailable", "detail": "device state invalid"}
    return value | {"io": io_snapshot()}


def loaded_models() -> list[dict[str, object]]:
    models: list[dict[str, object]] = []
    try:
        with urllib.request.urlopen(LEMONADE_HEALTH, timeout=2) as response:
            data = json.load(response)
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        data = {}
    rows = data.get("all_models_loaded", []) if isinstance(data, dict) else []
    models.extend(row | {"backend": "lemonade"} for row in rows if isinstance(row, dict) and row.get("loaded"))
    try:
        with urllib.request.urlopen(OLLAMA_MODELS, timeout=2) as response:
            data = json.load(response)
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        data = {}
    rows = data.get("models", []) if isinstance(data, dict) else []
    models.extend(row | {"backend": "ollama"} for row in rows if isinstance(row, dict))
    return models


def npu_snapshot(models: list[dict[str, object]], device: Path = NPU_DEVICE) -> dict[str, object]:
    if not device.exists():
        return {"availability": "unavailable", "summary": "XDNA NPU device not found", "models": []}
    names = [
        str(row.get("model_name") or row.get("name") or "unknown")
        for row in models
        if "flm" in json.dumps(row).lower() or "npu" in json.dumps(row).lower()
    ]
    return {
        "availability": "available",
        "summary": "NPU ready; active model: " + (", ".join(names) if names else "none identified"),
        "models": names,
    }


def snapshot(
    statuses: list[ServiceStatus] | None = None,
    *,
    models: list[dict[str, object]] | None = None,
    automation: list[dict[str, object]] | None = None,
    device_path: Path = DEVICE_STATE,
    npu_device: Path = NPU_DEVICE,
) -> dict[str, object]:
    statuses = probe_all(load_services()) if statuses is None else statuses
    models = loaded_models() if models is None else models
    automation = load_automation() if automation is None else automation
    services = [
        {"id": item.meta.id, "title": item.meta.title, "state": item.unit_state}
        for item in statuses
    ]
    healthy = sum(item.health_ok is not False and item.unit_state in ("active", "n/a") for item in statuses)
    return {
        "summary": f"{healthy}/{len(statuses)} services ready",
        "services": services,
        "automation": [
            {key: row.get(key) for key in ("task_id", "provider", "state", "branch")}
            for row in automation
            if row.get("task_id")
        ],
        "models": models,
        "platform": {"summary": "AI MAX+ 395 platform telemetry pending"},
        "runtime": {
            "summary": f"{len(models)} local model(s) loaded",
            "compact_idle_release": compact_idle_snapshot(models),
        },
        "device": device_snapshot(device_path),
        "npu": npu_snapshot(models, npu_device),
    }
