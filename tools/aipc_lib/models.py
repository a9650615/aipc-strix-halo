from __future__ import annotations

import os
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
    # Provisioning override (0015). "hf_xet" => this model's repo is on HF Xet
    # content-addressed storage with a stale LFS etag, so `lemonade pull`
    # fetches content-wrong bytes and verify-loops forever; sync must fetch it
    # with the hf_xet client instead. Requires `revision` (a pinned commit) so
    # provisioning is deterministic. Empty => normal `lemonade pull`.
    provision: str = ""
    revision: str = ""

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
            provision=str(raw.get("provision", "")),
            revision=str(raw.get("revision", "")),
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
    if entry.provision == "hf_xet":
        # Fetched by xet_provision_commands (hf_xet client), never lemonade pull
        # — pull would loop on the stale LFS etag (0015).
        return None
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


# Lemonade's HF cache (container /root/.cache/huggingface, host-mounted) and a
# user-writable staging cache the hf_xet client (in the invoking user's
# site-packages, not root's) can actually write to. Both live on the same
# btrfs here, so the materialise step reflinks (CoW, ~free); cross-fs falls
# back to a full copy via --reflink=auto.
LEMONADE_HF_HUB = Path("/var/lib/aipc-models/hf/hub")
# User-writable HF_HOME the hf_xet download stages into. Overridable so a
# deploy/verify run can point it at an existing HF cache (hf skips the fetch
# when the file is already there). Never a tmpfs path — a multi-GB pull would
# OOM the box.
XET_STAGING = Path(os.environ.get("AIPC_XET_STAGING") or (Path.home() / ".cache" / "aipc-xet"))

# Replicate one hf-CLI-produced HF repo cache dir (blobs + snapshot symlinks +
# refs) from staging into Lemonade's root-owned cache, reflinking blobs and
# preserving the relative snapshot symlinks, then force refs/main to the pinned
# commit and delete any Lemonade `.download_manifest.json`/`*.partial`. That
# manifest is Lemonade's "download in progress" marker: while it exists,
# ModelManager treats the model as not-downloaded and hands llama-server the
# repo DIRECTORY instead of the .gguf ("No such file"). Idempotent: existing
# blobs are left as-is, symlinks/refs are refreshed.
_XET_MATERIALIZE_SNIPPET = r'''
import os, subprocess, sys
src, dst, commit = sys.argv[1], sys.argv[2], sys.argv[3]
if not os.path.isdir(src):
    sys.exit("xet materialise: staging repo missing: " + src)
for base, _dirs, files in os.walk(src):
    rel = os.path.relpath(base, src)
    out = dst if rel == "." else os.path.join(dst, rel)
    os.makedirs(out, exist_ok=True)
    for name in files:
        sp, dp = os.path.join(base, name), os.path.join(out, name)
        if os.path.islink(sp):
            if os.path.lexists(dp):
                os.remove(dp)
            os.symlink(os.readlink(sp), dp)
        elif not os.path.exists(dp):
            if subprocess.run(["cp", "--reflink=auto", sp, dp]).returncode != 0:
                sys.exit("xet materialise: copy failed: " + sp)
refs = os.path.join(dst, "refs")
os.makedirs(refs, exist_ok=True)
with open(os.path.join(refs, "main"), "w") as fh:
    fh.write(commit)
for base, _dirs, files in os.walk(dst):
    for name in files:
        if name == ".download_manifest.json" or name.endswith(".partial"):
            os.remove(os.path.join(base, name))
'''


def _hf_repo_dirname(repo: str) -> str:
    """HF cache dir name for an owner/repo id (models--owner--repo)."""
    return "models--" + repo.replace("/", "--")


def xet_provision_commands(
    entry: ModelEntry,
    staging: Path = XET_STAGING,
    hub: Path = LEMONADE_HF_HUB,
) -> list[list[str]] | None:
    """Command sequence to provision a `provision: hf_xet` Lemonade model, or
    None if the entry is not hf_xet. Per checkpoint: fetch REPO:FILE with the
    hf_xet client (as the invoking user, HF_HOME in a user-writable staging
    dir — never /tmp, which is tmpfs=RAM) at the pinned revision, then reflink
    the completed cache layout into Lemonade's root-owned cache. Raises
    ValueError on a malformed hf_xet entry (missing revision / bad checkpoint).
    """
    if entry.provision != "hf_xet":
        return None
    if entry.backend != "lemonade" or not entry.checkpoints:
        raise ValueError(f"{entry.alias}: provision hf_xet needs a lemonade entry with checkpoints")
    if not entry.revision:
        raise ValueError(f"{entry.alias}: provision hf_xet requires a pinned 'revision'")
    cmds: list[list[str]] = []
    materialised: set[str] = set()
    for ref in entry.checkpoints.values():
        repo, sep, fname = ref.partition(":")
        if not sep or not fname:
            raise ValueError(f"{entry.alias}: checkpoint '{ref}' must be REPO:FILE")
        cmds.append(["env", f"HF_HOME={staging}", "hf", "download", repo, fname,
                     "--revision", entry.revision])
        if repo not in materialised:
            materialised.add(repo)
            src = staging / "hub" / _hf_repo_dirname(repo)
            dst = hub / _hf_repo_dirname(repo)
            cmds.append(["sudo", "python3", "-c", _XET_MATERIALIZE_SNIPPET,
                         str(src), str(dst), entry.revision])
    return cmds


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
        if entry.provision == "hf_xet":
            try:
                fetch_cmds = xet_provision_commands(entry)
            except ValueError:
                results.append((entry, False))  # malformed manifest entry
                continue
            success = all(runner(c, check=False).returncode == 0 for c in fetch_cmds)
        else:
            cmd = pull_command(entry)
            if cmd is None:
                continue
            success = runner(cmd, check=False).returncode == 0
        pin_cmd = recipe_pin_command(entry)
        if success and pin_cmd is not None:
            success = runner(pin_cmd, check=False).returncode == 0
        if success:
            entry.weights_path(models_root).mkdir(parents=True, exist_ok=True)
            entry.marker_path(models_root).write_text(entry.model_id + "\n")
        results.append((entry, success))
    return results
