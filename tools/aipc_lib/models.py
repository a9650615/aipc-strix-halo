from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


DEFAULT_MANIFEST = Path("/etc/aipc/models/models.yaml")
DEFAULT_MODELS_ROOT = Path("/var/lib/aipc-models")


@dataclass
class ModelEntry:
    alias: str
    backend: str
    model_id: str
    size_gb: float | None
    path: str

    @classmethod
    def from_dict(cls, raw: dict) -> "ModelEntry":
        return cls(
            alias=str(raw.get("alias", "")),
            backend=str(raw.get("backend", "")),
            model_id=str(raw.get("model_id", "")),
            size_gb=raw.get("size_gb"),
            path=str(raw.get("path", "")),
        )


def load_manifest(path: Path) -> list[ModelEntry]:
    """Parse models.yaml into a list of ModelEntry. Empty list if file missing."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [ModelEntry.from_dict(e) for e in data.get("models", []) or []]


def on_disk_status(entry: ModelEntry, models_root: Path) -> str:
    return "present" if (models_root / entry.path).exists() else "missing"


def sync_check(entries: list[ModelEntry], models_root: Path) -> list[ModelEntry]:
    """Return the subset of entries whose weights are not on disk."""
    return [e for e in entries if on_disk_status(e, models_root) == "missing"]
