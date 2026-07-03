from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from aipc_lib.models import DEFAULT_MANIFEST, load_manifest
from aipc_lib.modules import Module, discover

DEFAULT_OLLAMA_BASE = "http://127.0.0.1:11434"


@dataclass
class ModuleService:
    module: str
    service: str


def module_services(mod: Module) -> list[str]:
    """Service unit names this module ships, derived from its shipped files.

    Podman quadlets (quadlet/*.container) generate a same-named .service at
    runtime; plain systemd units under files/etc/systemd/system/*.service
    are copied in verbatim. Neither renderer emits any other service shape.
    """
    names: list[str] = []
    quadlet_dir = mod.path / "quadlet"
    if quadlet_dir.is_dir():
        for f in sorted(quadlet_dir.glob("*.container")):
            names.append(f"{f.stem}.service")

    unit_dir = mod.path / "files" / "etc" / "systemd" / "system"
    if unit_dir.is_dir():
        for f in sorted(unit_dir.glob("*.service")):
            names.append(f.name)

    return names


def discover_module_services(modules_root: Path) -> list[ModuleService]:
    """Every (module, service) pair for currently-enabled modules."""
    result: list[ModuleService] = []
    for mod in discover(modules_root):
        for svc in module_services(mod):
            result.append(ModuleService(module=mod.name, service=svc))
    return result


def service_is_active(service: str) -> str:
    proc = subprocess.run(
        ["systemctl", "is-active", service], capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() or "unknown"


def loaded_models(base_url: str = DEFAULT_OLLAMA_BASE) -> list[dict] | None:
    """Query Ollama's /api/ps. Returns None if Ollama isn't reachable."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/ps", timeout=3) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return data.get("models", [])


def alias_display_name(model_id: str, manifest_path: Path = DEFAULT_MANIFEST) -> str:
    """"alias (model_id)" for whichever models.yaml alias points at this
    ollama model_id (/api/ps reports the raw model_id, not the LiteLLM-
    facing alias) — same naming convention as `aipc config sync-opencode`,
    so the model column reads the same way across every aipc subcommand.
    Falls back to the bare model_id if nothing in the manifest matches
    (e.g. a model pulled by hand for testing, not yet registered)."""
    for entry in load_manifest(manifest_path):
        if entry.model_id == model_id:
            return f"{entry.alias} ({model_id})"
    return model_id
