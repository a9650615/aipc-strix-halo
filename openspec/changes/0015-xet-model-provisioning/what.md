# What

Add a Xet-aware provisioning path to `aipc models sync` so a model whose
weights live in HF Xet storage (and/or carry a stale LFS etag) can be fetched
reproducibly, without `lemonade pull`.

- A `models.yaml` entry MAY declare it must be provisioned via the Xet client
  (e.g. `provision: hf_xet`). Absent the flag, sync behaves exactly as today
  (`lemonade pull`), so no existing entry changes behaviour.
- For a flagged entry, `aipc models sync` SHALL fetch each `checkpoints` file
  with the `hf` (`hf_xet`) client into Lemonade's HF cache and leave the
  **completed** cache layout Lemonade treats as downloaded — `blobs/<etag>`,
  `snapshots/<commit>/<file>` symlink, `refs/main`, and **no**
  `.download_manifest.json` — then pin `recipe_options` and mark the model as
  synced exactly as the normal path does.
- Provisioning SHALL be **idempotent** (skip the fetch when the completed
  layout for the pinned commit is already present) and SHALL NOT run
  `lemonade pull` for the flagged entry.
- Integrity SHALL be established by the `hf_xet` client's own chunk-hash
  reconstruction and by a successful model **load**, NOT by comparing the blob
  to the LFS etag (which is expected to be stale for these repos).

`coder-agentic` (the SC117 native-MTP model) SHALL carry the flag so its live
hand-provisioning becomes reproducible.

Non-goals: changing Lemonade itself, changing how non-Xet models are pulled,
or moving weights into the baked image (they stay runtime-provisioned).
