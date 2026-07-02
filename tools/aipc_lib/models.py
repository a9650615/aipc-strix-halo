from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml


DEFAULT_MANIFEST = Path("/etc/aipc/models/models.yaml")
DEFAULT_MODELS_ROOT = Path("/var/lib/aipc-models")

# Backends whose weights live on disk under DEFAULT_MODELS_ROOT and need
# syncing. Everything else (anthropic/openai/google today; size_gb: cloud)
# is a remote API — no local weights, never "missing".
LOCAL_BACKENDS = {"ollama", "lemonade"}


@dataclass
class ModelEntry:
    alias: str
    backend: str
    model_id: str
    size_gb: Any = None

    @classmethod
    def from_dict(cls, raw: dict) -> "ModelEntry":
        return cls(
            alias=str(raw.get("alias", "")),
            backend=str(raw.get("backend", "")),
            model_id=str(raw.get("model_id", "")),
            size_gb=raw.get("size_gb"),
        )

    @property
    def is_cloud(self) -> bool:
        return self.backend not in LOCAL_BACKENDS

    def weights_path(self, models_root: Path) -> Path:
        # ponytail: aipc's own sync bookkeeping (backend/alias marker dir),
        # not a replica of each backend's real blob-store layout (e.g.
        # Ollama's registry manifest path). Good enough to answer "did aipc
        # models sync succeed for this alias"; revisit if that drifts from
        # what's actually loaded once verified on hardware (tasks.md #1.5).
        return models_root / self.backend / self.alias


def load_manifest(path: Path) -> list[ModelEntry]:
    """Parse models.yaml into a list of ModelEntry. Empty list if file missing."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [ModelEntry.from_dict(e) for e in data.get("models", []) or []]


def on_disk_status(entry: ModelEntry, models_root: Path) -> str:
    if entry.is_cloud:
        return "n/a"
    return "present" if entry.weights_path(models_root).exists() else "missing"


def sync_check(entries: list[ModelEntry], models_root: Path) -> list[ModelEntry]:
    """Return the subset of local-backend entries whose weights are not on disk."""
    return [e for e in entries if on_disk_status(e, models_root) == "missing"]


def pull_command(entry: ModelEntry) -> list[str] | None:
    """argv to fetch this entry's weights, or None if there's nothing to pull."""
    if entry.backend == "ollama":
        return ["ollama", "pull", entry.model_id]
    if entry.backend == "lemonade":
        # ponytail: host-side pull CLI unconfirmed — llm-lemonade's container
        # schema is still TODO-marked (tasks.md #1.5). Best-guess command;
        # revisit once verified against a running amd/lemonade-sdk container.
        return ["lemonade-server", "pull", entry.model_id]
    return None


def sync_pull(
    entries: list[ModelEntry],
    models_root: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[tuple[ModelEntry, bool]]:
    """Pull every missing, local-backend model. Returns (entry, success) pairs.

    Cloud-backend entries and already-present entries are skipped entirely —
    the runner is never invoked for them.
    """
    results: list[tuple[ModelEntry, bool]] = []
    for entry in sync_check(entries, models_root):
        cmd = pull_command(entry)
        if cmd is None:
            continue
        proc = runner(cmd, check=False)
        success = proc.returncode == 0
        if success:
            entry.weights_path(models_root).mkdir(parents=True, exist_ok=True)
        results.append((entry, success))
    return results
