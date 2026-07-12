# Tasks

- [ ] 1.1 models.py: `ModelEntry.provision` field; `pull_command` returns
      `None` for `provision == "hf_xet"`; `xet_provision(entry, models_root,
      runner)` builds the `hf download --revision <commit>` call and the
      completed-layout materialisation (reflink blob, snapshot symlink,
      refs/main, ensure no `.download_manifest.json`); idempotent skip when the
      layout for the pinned commit already exists.
- [ ] 1.2 models.py: `sync_pull` dispatches flagged entries to `xet_provision`
      (as primary user, never to `/tmp`), then pins `recipe_options` + writes
      the synced marker; `on_disk_status`/stale treats layout-present as
      synced without re-hashing against the (stale) etag.
- [ ] 1.3 models.yaml: `coder-agentic` gains `provision: hf_xet` + pinned
      commit; verify no other entry changes behaviour.
- [ ] 1.4 Provisioning deps: ensure the primary-user runtime environment that
      runs `aipc models sync` has `huggingface_hub[hf_xet]`; confirm the sync
      oneshot can `runuser` to that user for the `hf` call.
- [ ] 2.1 Static: unit tests (pull_command None for flagged; xet_provision
      argv + layout ops; idempotent skip; non-flagged unchanged; existing
      30 green); ruff; `openspec validate 0015-xet-model-provisioning
      --strict`.
- [ ] 2.2 Render: `aipc render bootc` / `aipc render ansible` green, §4 parity.
- [ ] 3.1 Hardware: on the live box wipe the SC117 model cache + marker, run
      `aipc models sync`, confirm hf_xet provisioning (no `.partial` loop),
      Lemonade counts it downloaded, `coder-agentic` loads and answers via the
      gateway. Fold back any path/permission findings.
