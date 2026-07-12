# Tasks

- [x] 1.1 models.py: `ModelEntry.provision` field; `pull_command` returns
      `None` for `provision == "hf_xet"`; `xet_provision(entry, models_root,
      runner)` builds the `hf download --revision <commit>` call and the
      completed-layout materialisation (reflink blob, snapshot symlink,
      refs/main, ensure no `.download_manifest.json`); idempotent skip when the
      layout for the pinned commit already exists.
- [x] 1.2 models.py: `sync_pull` dispatches flagged entries to `xet_provision`
      (as primary user, never to `/tmp`), then pins `recipe_options` + writes
      the synced marker; `on_disk_status`/stale treats layout-present as
      synced without re-hashing against the (stale) etag.
- [x] 1.3 models.yaml: `coder-agentic` gains `provision: hf_xet` + pinned
      commit; verify no other entry changes behaviour.
- [x] 1.4 Provisioning deps: `huggingface_hub[hf_xet]>=0.30` added to aipc's
      `pyproject.toml` — installing aipc now pulls the Xet client + the `hf`
      CLI onto the same PATH, so `hf download` is available wherever
      `aipc models sync` runs. `AIPC_XET_STAGING` env override added so a
      deploy/verify can point staging at an existing HF cache.
- [x] 2.1 Static: unit tests (pull_command None for flagged; xet_provision
      argv + layout ops; idempotent skip; non-flagged unchanged; existing
      30 green); ruff; `openspec validate 0015-xet-model-provisioning
      --strict`.
- [x] 2.2 Render: `aipc render bootc` / `aipc render ansible` green, §4 parity.
- [x] 3.1 Hardware (non-destructive): forced the live coder-agentic marker
      stale and ran the real `sync_pull` xet path on the box with
      `AIPC_XET_STAGING` pointed at the existing hf_xet download, so the
      `hf download` step hit cache (no 24GB re-fetch) while the full
      orchestration ran for real: dispatch → hf download → sudo materialise
      into Lemonade's cache → recipe pin → marker → status `present` in ~1s,
      no `.partial` loop. Verified the live cache stayed intact (blob +
      snapshot symlink + refs/main, no download manifest), `lemonade list`
      still reports the model downloaded, and the 0012 scheduler manifest now
      carries the correct model_id/size. NOT exercised: a literal cold 24GB
      Xet re-fetch (deliberately served from cache to avoid disrupting the
      in-use model / bandwidth) — the `hf download` fetch step is already
      hardware-proven (it is how the live gguf was originally obtained).
