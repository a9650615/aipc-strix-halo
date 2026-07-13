# How

## Live provisioning (already done, hardware-verified 2026-07-14)

Registered the borrowed mmproj onto the AEON user model, following
`tools/aipc_lib/models.py::pull_command`:

```
sudo podman exec lemonade /opt/lemonade/lemonade pull \
  user.Ornith-1.0-35B-AEON-Ultimate-Uncensored-MTP-Q4_K_M \
  --checkpoint main "mrexodia/Ornith-1.0-35B-AEON-Ultimate-Uncensored-MTP-GGUF:Ornith-1.0-35B-AEON-Ultimate-Uncensored-MTP-Q4_K_M.gguf" \
  --checkpoint mmproj "SC117/Ornith-1.0-35B-MTP-APEX-GGUF:mmproj-F16.gguf" \
  --recipe llamacpp --label tool-calling --label mtp --label vision
```

Note: `--label custom` is rejected by the pull CLI (auto-applied); the valid
set is `{coding,embeddings,hot,mtp,reasoning,reranking,tool-calling,vision}`.
The mmproj `.gguf` was already on disk (the APEX registration carries it), so
this was a zero-download re-registration. `recipe_options` (`-np 4 -kvu`,
vulkan) survived the re-pull; no `recipe_pin` needed.

## Hardware-verified evidence (via litellm `ornith-35b`, :4000)

| Test | Prompt | Reply | Time |
|---|---|---|---|
| OCR | text inside the red box | `VISION 7291` (exact) | 2.2s |
| Scene | shapes + colors, left→right | blue circle / red square / green triangle (all correct) | 1.7s |

The abliterate/uncensor fine-tune did **not** degrade vision on these tasks —
the projector aligns into AEON's embedding space fine. MTP tensors + mmproj +
`-np 4` coexist (consistent with the APEX finding, speculative decoding off).

## Repo edits (this change)

Reality-sync only — the four files listed in `what.md`. Update the
prose comment blocks in `models.yaml`/`config.yaml` so they describe AEON +
borrowed mmproj (and the drift that motivated this), not the old APEX story.

## Verification tiers

- Static: `openspec validate --strict`, ruff/shellcheck on touched files.
- Render: `tools/aipc render bootc`, `tools/aipc render ansible --check` — both
  targets stay in sync (only data/strings changed).
- Hardware: already reached (table above). A rebuilt image reaching this state
  is proven by `aipc models sync` fetching the AEON main + borrowed mmproj and
  a vision request succeeding through `ornith-35b`.
