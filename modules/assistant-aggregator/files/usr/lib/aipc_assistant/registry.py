"""Feature / slot registry for the aggregator hub."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aipc_assistant.paths import features_path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


@dataclass
class Pack:
    name: str
    slot: str  # entry|control|context|backend|output|pack
    enabled: bool = True
    commands: dict[str, Callable[..., Any]] = field(default_factory=dict)
    description: str = ""


_PACKS: dict[str, Pack] = {}


def register(pack: Pack) -> None:
    _PACKS[pack.name] = pack


def get(name: str) -> Pack | None:
    return _PACKS.get(name)


def list_packs() -> list[Pack]:
    return list(_PACKS.values())


def load_features_config(path: Path | None = None) -> dict[str, Any]:
    p = path or features_path()
    if not p.is_file() or yaml is None:
        return {"slots": {}, "packs": {}}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {"slots": {}, "packs": {}}


def is_pack_enabled(name: str, path: Path | None = None) -> bool:
    cfg = load_features_config(path)
    packs = cfg.get("packs") or {}
    if name in packs:
        return bool(packs[name])
    pack = _PACKS.get(name)
    return bool(pack and pack.enabled)


def bootstrap_builtin() -> None:
    """Register core logical packs (implementation may still be inline)."""
    if _PACKS:
        return
    for name, slot, desc in (
        ("keywords", "control", "YAML keyword actions"),
        ("controller", "control", "Local small-model control via LiteLLM"),
        ("context", "context", "persona/datetime/mem0 bundle"),
        ("backend_local", "backend", "agent-orchestrator :4100"),
        ("backend_online", "backend", "assistant-chatgpt Chromium"),
        ("handoff", "pack", "local→online spoken handoff"),
        ("system_audio", "pack", "PipeWire system audio share"),
        ("project", "pack", "ChatGPT Projects navigation"),
        ("gpt", "pack", "Custom GPT open"),
        ("upload", "pack", "file upload"),
        ("canvas", "pack", "canvas extract"),
        ("capture", "pack", "screen region inject"),
        ("tasks", "pack", "scheduled tasks UI"),
    ):
        register(Pack(name=name, slot=slot, enabled=True, description=desc))
