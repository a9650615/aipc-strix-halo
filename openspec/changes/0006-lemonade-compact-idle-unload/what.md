# What: Add Per-Alias Idle Unload Policy For Compact Models

Add a model-residency policy for Lemonade-backed aliases that can unload an
individual model after a configured idle period. The initial policy applies to
`coder-compact` only and unloads it after `300s` of inactivity.

The change introduces two pieces:

1. A per-alias idle policy field in `models.yaml` so residency rules live next
   to the model declaration and can later be applied to other aliases.
2. A Lemonade-side idle-release job that checks loaded models, compares each
   model's `last_use` age against the declared threshold, and calls
   `POST /api/v0/unload` for eligible non-pinned models.

## Capability Impact

- `ai-runtime`: Lemonade-backed compact aliases gain deterministic idle
  release.
- `llm-models`: model metadata gains an optional idle policy field.
- `llm-lemonade`: the runtime gains the loader that enforces the policy.

## Specification Diffs

### `modules/llm-models/files/etc/aipc/models/models.yaml`

- Add an optional `idle_unload_after_s` field to Lemonade model entries.
- Set `coder-compact.idle_unload_after_s = 300`.
- Leave all other aliases unchanged unless they explicitly opt in later.

### `modules/llm-lemonade`

- Add a small idle-release unit that runs on a timer and inspects Lemonade's
  health payload.
- The unit unloads only models that are loaded, not pinned, opted in, and idle
  longer than their threshold.
