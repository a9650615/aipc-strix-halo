# Tasks

- [x] 0.1 models.py: stale-marker detection (marker file records model_id),
      `checkpoints/recipe/label` manifest fields drive custom Lemonade
      registration pulls; cli list/sync surface "stale"; 26 unit tests.
- [x] 1.1 hermes_sync.py: LiteLLM-driven rewrite of custom_providers models
      (atomic write + .bak), unit tests (entry found/missing, override
      preserved, comment-free round-trip).
- [x] 1.2 cli.py: `aipc providers sync` group command (per-consumer
      SKIPPED/synced reporting); `aipc models sync` auto-runs it after a
      successful pull (`--no-providers` opt-out).
- [x] 1.3 Static + render: pytest, ruff, `aipc render bootc` /
      `aipc render ansible` green.
- [x] 2.1 HW: `aipc providers sync` run on the live box 2026-07-12 —
      opencode 14 / ccs 8 / hermes 9 models synced, Hermes config keys
      outside custom_providers untouched, coder-122b present everywhere.
      Hermes config reread-vs-restart not yet observed — restart Hermes if
      the new aliases don't show in its picker.
