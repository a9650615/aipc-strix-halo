# How

## `tools/aipc_lib/models.py`

- `ModelEntry`: add `provision: str | None` (parsed from the manifest;
  `"hf_xet"` is the only value for now). Default `None` = today's behaviour.
- `pull_command(entry)`: return `None` for a `provision == "hf_xet"` entry so
  the normal `lemonade pull` path is skipped for it.
- New `xet_provision(entry, models_root, runner)`: for each `checkpoints`
  value `REPO:FILE`, resolve the pinned commit (from the manifest or the HF
  API), and if the completed layout for that commit is not already present,
  run `hf download REPO FILE --revision <commit>` **as the primary user**
  (hf_xet lives in the user's site-packages; `sudo`/root cannot see it — see
  the ops-firstboot `runuser -u` pattern) into a user-writable HF cache, then
  materialise the layout into Lemonade's root-owned cache
  (`/var/lib/aipc-models/hf/hub/models--<owner>--<repo>/`): reflink the blob
  (same btrfs → CoW), create the `snapshots/<commit>/<file>` symlink and
  `refs/main`, and ensure **no** `.download_manifest.json` remains. Never
  download to `/tmp` (tmpfs = RAM → a multi-GB pull OOMs the box).
- `sync_pull(...)`: dispatch flagged entries to `xet_provision` instead of the
  pull command, then pin `recipe_options` and write the synced marker as usual.
- `on_disk_status` / stale detection: treat a Xet entry as present when the
  completed layout for the pinned commit exists (do not re-hash against the
  etag).

## `models.yaml`

- `coder-agentic` gains `provision: hf_xet`. The commit hash is pinned in the
  `checkpoints` ref or a sibling `revision:` field so provisioning is
  deterministic and offline-idempotent.

## Runtime provisioning

- The existing runtime model-sync oneshot already runs `aipc models sync`;
  no new unit is needed. Confirm it runs in a context that can `runuser` to
  the primary user for the `hf` call (same requirement as other user-context
  runtime steps), and that `huggingface_hub[hf_xet]` is present in that user
  environment (add to the provisioning deps if not).

## Tests

- Unit: `pull_command` returns `None` for a flagged entry; `xet_provision`
  builds the expected `hf download` argv and layout operations (stub
  `runner`/fs); idempotent skip when the layout exists; non-flagged entries
  unchanged. Keep the existing 30 models.py tests green.
- Render: `aipc render bootc` / `aipc render ansible` green, §4 parity.
- Hardware: on the live box, remove the model's cache + marker, run
  `aipc models sync`, confirm it provisions via hf_xet (no `.partial` loop),
  Lemonade counts it downloaded, and `coder-agentic` loads and answers.
