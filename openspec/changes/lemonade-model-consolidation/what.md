# What: Unify Model Weights Under `/var/lib/aipc-models`

All model weights — Ollama blobs **and** Lemonade HuggingFace downloads —
SHALL live under the single shared root `/var/lib/aipc-models` (the tree
`aipc-models-dir.service` already resolves to the primary user's
`~/aipc-models`).

Ollama is already there (unchanged). Lemonade's HF cache moves from
`/var/lib/aipc-lemonade/huggingface` to `/var/lib/aipc-models/hf`, mounted
into the container at the same guest path (`/root/.cache/huggingface`), so
Lemonade's internal cache layout is unchanged — only the host bind source
moves under the shared root.

## Layout after this change

```
/var/lib/aipc-models/        (symlink → ~/aipc-models)
├── blobs/                    Ollama weights (unchanged)
├── manifests/                Ollama manifests (unchanged)
└── hf/hub/models--...        Lemonade HF cache (MOVED here)
```

Lemonade's two **non-weight** mounts are deliberately left in place:
`/var/lib/aipc-lemonade/cache` (lemonade `config.json`/`user_models.json`) and
`/var/lib/aipc-lemonade/flm` (FLM backend state) are not model weights and do
not belong in the shared model root.

## Capabilities

- Modifies capability: `ai-runtime` (the `llm-lemonade` module's persisted
  mount layout).
- No new capability.
- No change to the LiteLLM contract (§7): backends are still addressed by
  alias through the gateway; only where Lemonade stores pulled weights changes.

## Specification Diffs (Targeting Modules)

`modules/llm-lemonade/files/etc/systemd/system/lemonade.service`:
- `ExecStartPre` mkdir target for the HF cache changes from
  `/var/lib/aipc-lemonade/huggingface` to `/var/lib/aipc-models/hf`.
- The HF cache bind volume changes from
  `-v /var/lib/aipc-lemonade/huggingface:/root/.cache/huggingface:Z` to
  `-v /var/lib/aipc-models/hf:/root/.cache/huggingface:Z`.
- The other two Lemonade mounts (`cache`, `flm`) are unchanged.
