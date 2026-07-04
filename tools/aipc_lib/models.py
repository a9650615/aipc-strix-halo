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
        # Ollama runs as a root-owned system quadlet (modules/llm-ollama),
        # not a host binary — hardware-verified 2026-07-03 that a bare
        # `ollama pull` here has no daemon to reach (no host-side `ollama`
        # CLI/socket at all) and instead a caller talking to the daemon
        # over HTTP for a not-yet-pulled model just gets repeated 404s.
        # Pull has to go through the container itself, same as
        # config_menu.py already does for `sudo systemctl restart`.
        return ["sudo", "podman", "exec", "ollama", "ollama", "pull", entry.model_id]
    if entry.backend == "lemonade":
        # Following the pattern of ollama backend: pull via the container
        # itself. Binary is /opt/lemonade/lemonade (the CLI client talking
        # to lemond, the server it runs alongside) — hardware-verified
        # 2026-07-04 there is no "lemonade-server" binary/alias in the
        # image, that was a pre-verification guess. Like Ollama, a pulled
        # model auto-loads on its first inference request — no separate
        # "load" step needed here.
        return [
            "sudo",
            "podman",
            "exec",
            "lemonade",
            "/opt/lemonade/lemonade",
            "pull",
            entry.model_id,
        ]
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
