# Hermes Provider-Aware Compression Design

**Date:** 2026-07-17  
**Status:** Approved by user

## Goal

Keep Hermes context compression on the same online provider/model as an online
conversation, while using the dedicated local `coder-compact` model only when
the active conversation uses the local provider.

## Current problem

`~/.hermes/config.yaml` currently pins `auxiliary.compression` to
`custom:local` + `coder-compact`. That makes online conversations compress
through the local endpoint. Hermes' existing `auto` route does the opposite
of the local requirement: it follows the active main model, so a local
conversation would compress with its full local main model instead of the
dedicated compact model.

## Design

Keep the main model/provider selectable at runtime. Configure compression as an
auto route with a local-only model override:

```yaml
auxiliary:
  compression:
    provider: auto
    model: auto
    local_model: coder-compact
```

Extend the existing auxiliary resolver at its `task="compression"` decision
point:

1. Resolve the active main provider and model exactly as today.
2. If the active provider is the local provider (`custom:local`/its normalized
   local identity), route compression to `custom:local` with
   `auxiliary.compression.local_model`.
3. Otherwise, preserve the existing main-provider/main-model route unchanged.

This does not hardcode an online model. `openai-codex`, `custom:cliproxy`,
`xai-oauth`, and other online providers keep their active provider, model, and
API transport. The current online Codex subscription model will be smoke-tested
before it is made the Hermes default.

## Scope

Modify only the Hermes auxiliary resolver and its focused tests, plus the
home-managed Hermes config. Leave vision, title generation, web extraction,
session search, fallback policy, OAuth files, and the repository's unrelated
working-tree changes untouched.

## Error handling

Use Hermes' existing auxiliary failure and compression fallback behavior. The
new branch only selects the route; it does not add retries, credentials, or a
new endpoint. A missing local `coder-compact` model remains an existing local
compression failure rather than silently sending local data to an online
provider.

## Verification

- Static: Hermes focused resolver tests pass in its existing virtualenv.
- Route contract: an online main provider/model resolves to that same online
  provider/model; `custom:local` resolves to `custom:local/coder-compact`.
- Regression: non-compression auxiliary tasks retain their current resolution.
- Runtime: one minimal request through the verified Codex subscription model
  and one local route check; no credentials are printed.

## Non-goals

- No new online model alias or API key.
- No change to LiteLLM routing or repository module renderers.
- No automatic switching of the main conversation between online and local;
  only compression follows the active provider.
