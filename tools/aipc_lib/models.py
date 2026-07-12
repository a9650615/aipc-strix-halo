from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml


DEFAULT_MANIFEST = Path("/etc/aipc/models/models.yaml")
DEFAULT_MODELS_ROOT = Path("/var/lib/aipc-models")

# Backends whose weights live on disk under DEFAULT_MODELS_ROOT and need
# syncing. Everything else (anthropic/openai/google today; size_gb: cloud)
# is a remote API — no local weights, never "missing".
LOCAL_BACKENDS = {"ollama", "lemonade"}

MARKER_FILE = "model_id"


@dataclass
class ModelEntry:
    alias: str
    backend: str
    model_id: str
    size_gb: Any = None
    # Lemonade custom (non-catalog) registrations: HF repo:file refs keyed by
    # checkpoint slot (main/draft/mmproj). Presence of any checkpoint switches
    # the pull to the user.-prefixed registration form.
    checkpoints: dict[str, str] = field(default_factory=dict)
    recipe: str = ""
    labels: list[str] = field(default_factory=list)
    # Saved llama-server load options (ctx_size, llamacpp_args, ...). Written
    # into lemonade's recipe_options.json by sync AFTER the pull and BEFORE
    # any load — hardware-verified 2026-07-12 that an unpinned first load of
    # a big model uses the model-card ctx (262144 for coder-122b), exhausts
    # GTT and DeviceLost-crashes every GPU context on the box.
    recipe_options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "ModelEntry":
        label = raw.get("label") or []
        return cls(
            alias=str(raw.get("alias", "")),
            backend=str(raw.get("backend", "")),
            model_id=str(raw.get("model_id", "")),
            size_gb=raw.get("size_gb"),
            checkpoints=dict(raw.get("checkpoints") or {}),
            recipe=str(raw.get("recipe", "")),
            labels=[label] if isinstance(label, str) else [str(x) for x in label],
            recipe_options=dict(raw.get("recipe_options") or {}),
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

    def marker_path(self, models_root: Path) -> Path:
        return self.weights_path(models_root) / MARKER_FILE


def load_manifest(path: Path) -> list[ModelEntry]:
    """Parse models.yaml into a list of ModelEntry. Empty list if file missing."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [ModelEntry.from_dict(e) for e in data.get("models", []) or []]


def on_disk_status(entry: ModelEntry, models_root: Path) -> str:
    """present / stale / missing / n-a for one manifest entry.

    The marker dir alone only proves the ALIAS was synced at some point; the
    model behind an alias changes (that is the whole point of the alias
    layer), so the marker file inside records WHICH model_id was synced.
    A dir without the file (pre-marker syncs) or with a different id reads
    "stale" — sync_check treats that the same as missing, which is what
    makes a models.yaml swap converge on the next `aipc models sync`.
    """
    if entry.is_cloud:
        return "n/a"
    marker = entry.marker_path(models_root)
    if not marker.parent.exists():
        return "missing"
    if not marker.exists() or marker.read_text().strip() != entry.model_id:
        return "stale"
    return "present"


def sync_check(entries: list[ModelEntry], models_root: Path) -> list[ModelEntry]:
    """Return the local-backend entries whose synced weights are missing or stale."""
    return [e for e in entries if on_disk_status(e, models_root) in ("missing", "stale")]


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
        cmd = ["sudo", "podman", "exec", "lemonade", "/opt/lemonade/lemonade", "pull"]
        if entry.checkpoints:
            # Custom HF registration: pull must target the user.-prefixed id
            # and carry the checkpoint refs; re-running it against an
            # existing registration is idempotent (and how draft/mmproj
            # checkpoints get added — see assistant-gemma in models.yaml).
            cmd.append(f"user.{entry.model_id}")
            for slot, ref in entry.checkpoints.items():
                cmd += ["--checkpoint", slot, ref]
            cmd += ["--recipe", entry.recipe or "llamacpp"]
            for label in entry.labels:
                cmd += ["--label", label]
        else:
            cmd.append(entry.model_id)
        return cmd
    return None


# Host-side path of lemonade's saved per-model load options (the container
# volume /root/.cache/lemonade — see modules/llm-lemonade quadlet).
RECIPE_OPTIONS_PATH = "/var/lib/aipc-lemonade/cache/recipe_options.json"

_RECIPE_PIN_SNIPPET = """\
import json, sys
key, patch, path = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3]
try:
    d = json.load(open(path))
except FileNotFoundError:
    d = {}
d[key] = patch
json.dump(d, open(path, "w"), indent=2)
"""


def recipe_pin_command(entry: ModelEntry) -> list[str] | None:
    """argv that pins this entry's recipe_options into lemonade's saved
    options file, or None if there is nothing to pin.

    ponytail: only custom (checkpoints-registered, user.-prefixed) lemonade
    models supported — builtin-catalog keys use a different prefix; add it
    when a builtin model first needs pinning. Pins are read by lemond at
    load time; restart lemonade if a load already ran unpinned.
    """
    if entry.backend != "lemonade" or not entry.recipe_options or not entry.checkpoints:
        return None
    import json

    return [
        "sudo",
        "python3",
        "-c",
        _RECIPE_PIN_SNIPPET,
        f"user.{entry.model_id}",
        json.dumps(entry.recipe_options),
        RECIPE_OPTIONS_PATH,
    ]


def sync_pull(
    entries: list[ModelEntry],
    models_root: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[tuple[ModelEntry, bool]]:
    """Pull every missing or stale local-backend model. Returns (entry, success) pairs.

    Cloud-backend entries and already-present entries are skipped entirely —
    the runner is never invoked for them. Entries carrying recipe_options
    are pinned after the pull; the marker (and success) requires BOTH, so a
    failed pin is retried on the next sync instead of silently lost.
    """
    results: list[tuple[ModelEntry, bool]] = []
    for entry in sync_check(entries, models_root):
        cmd = pull_command(entry)
        if cmd is None:
            continue
        proc = runner(cmd, check=False)
        success = proc.returncode == 0
        pin_cmd = recipe_pin_command(entry)
        if success and pin_cmd is not None:
            success = runner(pin_cmd, check=False).returncode == 0
        if success:
            entry.weights_path(models_root).mkdir(parents=True, exist_ok=True)
            entry.marker_path(models_root).write_text(entry.model_id + "\n")
        results.append((entry, success))
    return results
