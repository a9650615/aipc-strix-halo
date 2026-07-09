"""Local-model role presets for 128GB UMA (not full mutual exclusion).

Always-on closed loop / baseline (user standing decision 2026-07-10;
change only if a better combo is hardware-proven). Product write-up:
docs/voice-pipeline.md and docs/architecture.md Phase 3.

  - resident-small  (Lemonade FLM / NPU — default /chat brain)
  - SenseVoice      (STT — outside this module, never unload here)
  - Kokoro          (TTS — outside this module)
  - mem0            (memory — outside this module)
  - portal          (manage UI — outside this module)

Role layer (heavy, exclusive with each other; optional on top of the loop):
  - agent: Lemonade Vulkan agent LLMs (qwythos / coder-agentic / ornith / …)
  - 122b:  Ollama qwen35-122b-q3 (~81GB) — cannot co-reside with agent Vulkan

`aipc models use` only plans LLM unload/warm. The closed loop (STT/TTS/
mem0/portal + NPU resident-small) stays up regardless of preset.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from aipc_lib.models import ModelEntry

# Preset id -> human summary
PRESETS: dict[str, str] = {
    "agent": (
        "Agent role: Lemonade agent stack (qwythos-9b / coder-agentic / "
        "assistant-gemma / ornith). Unloads giant Ollama 122B. Baseline "
        "(resident-small + SenseVoice + Kokoro + mem0) stays."
    ),
    "122b": (
        "Dev/coding role: giant Qwen3.5-122B on Ollama. Unloads Lemonade "
        "Vulkan agent LLMs; keeps NPU resident-small. Baseline STT/TTS/mem0 "
        "stay as services."
    ),
    "free": (
        "Unload heavy role LLMs (Ollama giants + Lemonade Vulkan). "
        "Keeps NPU resident-small; baseline voice/mem0 services untouched."
    ),
}

# Aliases treated as "giant" Ollama models for agent/free switches.
GIANT_OLLAMA_ALIASES = frozenset({"qwen35-122b-q3"})

# Lemonade aliases never torn down for role switches (baseline NPU small).
LEMONADE_KEEP_ON_122B = frozenset({"resident-small"})


@dataclass(frozen=True)
class UnloadAction:
    alias: str
    backend: str
    model_id: str


@dataclass(frozen=True)
class WarmAction:
    """Optional post-switch warm so the first user request is faster."""

    alias: str
    backend: str
    model_id: str


@dataclass(frozen=True)
class SwitchPlan:
    preset: str
    unloads: list[UnloadAction]
    warm: WarmAction | None
    notes: list[str]


def _is_lemonade_keep(entry: ModelEntry) -> bool:
    if entry.alias in LEMONADE_KEEP_ON_122B:
        return True
    # FLM/NPU models must not be torn down for 122B (different backend budget).
    mid = entry.model_id.lower()
    return "flm" in mid or mid.endswith("-npu")


def plan_switch(
    preset: str,
    entries: Iterable[ModelEntry],
    *,
    loaded_ollama_ids: set[str] | None = None,
    loaded_lemonade_ids: set[str] | None = None,
) -> SwitchPlan:
    """Build unload/warm plan for a preset.

    If loaded_* sets are None, plan unloads for every matching declared
    local alias (safe offline planning / dry-run). If provided, only
    unload models currently reported loaded.
    """
    if preset not in PRESETS:
        known = ", ".join(sorted(PRESETS))
        raise ValueError(f"unknown preset {preset!r}; choose one of: {known}")

    by_alias = {e.alias: e for e in entries}
    unloads: list[UnloadAction] = []
    notes: list[str] = []
    warm: WarmAction | None = None

    def maybe_unload(entry: ModelEntry) -> None:
        if entry.is_cloud:
            return
        if loaded_ollama_ids is not None and entry.backend == "ollama":
            if not ollama_id_loaded(entry.model_id, loaded_ollama_ids):
                return
        if loaded_lemonade_ids is not None and entry.backend == "lemonade":
            if entry.model_id not in loaded_lemonade_ids:
                return
        unloads.append(
            UnloadAction(alias=entry.alias, backend=entry.backend, model_id=entry.model_id)
        )

    if preset == "agent":
        for alias in GIANT_OLLAMA_ALIASES:
            e = by_alias.get(alias)
            if e is not None:
                maybe_unload(e)
        notes.append(
            "Prefer LiteLLM: qwythos-9b (hermes), coder-agentic, or assistant-gemma."
        )
        # Warm hermes brain if declared, else coder-agentic.
        for warm_alias in ("qwythos-9b", "coder-agentic"):
            agent = by_alias.get(warm_alias)
            if agent is not None and agent.backend == "lemonade":
                warm = WarmAction(
                    alias=agent.alias, backend=agent.backend, model_id=agent.model_id
                )
                break

    elif preset == "122b":
        for e in by_alias.values():
            if e.backend == "lemonade" and not _is_lemonade_keep(e):
                maybe_unload(e)
        # Also unload other ollama models that aren't the giant (rare).
        giant = by_alias.get("qwen35-122b-q3")
        for e in by_alias.values():
            if e.backend == "ollama" and e.alias not in GIANT_OLLAMA_ALIASES:
                maybe_unload(e)
        if giant is not None:
            warm = WarmAction(alias=giant.alias, backend=giant.backend, model_id=giant.model_id)
        notes.append("Prefer LiteLLM alias qwen35-122b-q3.")
        notes.append("NPU resident-small is left alone if loaded.")

    elif preset == "free":
        for e in by_alias.values():
            if e.backend == "ollama":
                maybe_unload(e)
            elif e.backend == "lemonade" and not _is_lemonade_keep(e):
                maybe_unload(e)
        notes.append("Heavy local models unloaded; NPU resident-small kept.")

    # Deduplicate unloads by (backend, model_id)
    seen: set[tuple[str, str]] = set()
    deduped: list[UnloadAction] = []
    for u in unloads:
        key = (u.backend, u.model_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(u)

    return SwitchPlan(preset=preset, unloads=deduped, warm=warm, notes=notes)


def ollama_id_loaded(model_id: str, loaded_names: Iterable[str]) -> bool:
    """True if model_id matches any Ollama /api/ps name (tag-flexible)."""
    names = list(loaded_names)
    if model_id in names:
        return True
    return any(model_id in n or n in model_id for n in names)
