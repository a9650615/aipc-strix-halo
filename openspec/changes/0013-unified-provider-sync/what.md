# What: One Provider-Sync Entry Point Covering Hermes + CCS + OpenCode, Run Automatically After Model Changes — And Weight-Sync That Detects Swaps

## Weight-sync convergence (aipc models list/sync)

Same user requirement, weight-side: `aipc models list/sync` could not detect a
swapped model behind an alias (the on-disk marker recorded only the alias) and
could not pull custom Lemonade registrations at all (the `user.`-prefixed
`--checkpoint` pull existed only in models.yaml comments).

- The sync marker records the synced `model_id`; a mismatch (or a pre-marker
  dir) reads **stale** — `list` shows it, `sync` re-pulls it.
- models.yaml entries gain `checkpoints:` (slot → HF `repo:file`/`repo:QUANT`
  ref), `recipe:`, `label:` — `aipc models sync` builds the full custom
  registration pull from them.
- models.yaml entries gain `recipe_options:` (ctx_size / llamacpp_args /
  llamacpp_backend) — sync pins them into lemonade's `recipe_options.json`
  after the pull and before any load; the sync marker requires the pin to
  succeed. Motivation is a hardware incident, not tidiness: an unpinned
  first load uses the model-card ctx, and for `coder-122b` (ctx 262144)
  that exhausted GTT and DeviceLost-crashed every GPU context on the box
  (2026-07-12, see 0012).

- New `aipc providers sync`: runs every consumer sync (OpenCode, CCS, Hermes)
  against LiteLLM `/v1/models`, reporting per-consumer results; consumers
  whose config file is absent are skipped with a note, not an error.
- New Hermes sync (`hermes_sync.py`): rewrites the `local` entry in
  `~/.hermes/config.yaml` `custom_providers[].models` to the current local
  chat alias list (same NON_CHAT/cloud exclusions as OpenCode), preserving
  per-model `context_length` defaults. Atomic write + timestamped backup
  (Hermes has a history of corrupt-config incidents).
- `aipc models sync` runs `providers sync` automatically after a successful
  pull pass — swapping a model in models.yaml converges consumer configs in
  the same command, no separate step to remember.

## Capability Impact

- `ai-runtime`: the logical model namespace propagates to registered
  consumers automatically; hand-edited copies are eliminated.
