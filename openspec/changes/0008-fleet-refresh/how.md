# How: Pull/Load Recipes For Each Swap, and the MTP Wiring Detail

## 1. `vlm-screen` — new custom registration (main + mmproj)

```sh
lemonade pull user.Qwen3VL-8B-Instruct-Q4_K_M \
  --checkpoint main Qwen/Qwen3-VL-8B-Instruct-GGUF:Qwen3VL-8B-Instruct-Q4_K_M.gguf \
  --checkpoint mmproj Qwen/Qwen3-VL-8B-Instruct-GGUF:mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf \
  --recipe llamacpp --label vision
lemonade load Qwen3VL-8B-Instruct-Q4_K_M \
  --llamacpp vulkan --ctx-size 131072 \
  --llamacpp-args "-np 1 -kvu" --save-options
```

- Uses full filenames after the `:` for `main`/`mmproj` (per the official
  "Add a Custom Model" doc's multi-checkpoint example), not the short
  quant-tag shorthand (`:Q4_K_M`) this repo's existing custom entries use
  for a single `main` checkpoint — the doc's own example for a `main`+
  `mmproj` pair uses full filenames, so this recipe follows that rather
  than guessing whether the short form resolves against a `mmproj-`
  prefixed sibling.
- `-np 1 -kvu`: a screen-description/OCR lane is not a fan-out lane — same
  single-slot reasoning `coder-compact` already uses.
- `--ctx-size 131072`: conservative default well under the card's 256k
  native window; screen descriptions are short-lived requests, and this
  keeps KV cache small on a lane that competes for iGPU/GTT with whatever
  else is resident. Raise if a real use case needs more (see `coder-agentic`
  README comment for the same trade-off pattern).

## 2. `coder-compact` — re-pull under the new repo

```sh
lemonade pull user.Qwen3.5-4B-UD-Q4_K_XL \
  --checkpoint main unsloth/Qwen3.5-4B-GGUF:UD-Q4_K_XL \
  --recipe llamacpp --label tool-calling
lemonade load Qwen3.5-4B-UD-Q4_K_XL \
  --llamacpp vulkan --ctx-size 262144 \
  --llamacpp-args "-np 1 -kvu" --save-options
```

- Short quant-tag form (`:UD-Q4_K_XL`) kept for `main` — matches this
  repo's existing convention for single-checkpoint custom pulls
  (`coder-compact`'s own prior entry, `coder-agentic`, `ornith-35b` below).
- `--ctx-size 262144`: matches the card's native window; Gated DeltaNet's
  linear-attention layers keep KV growth sub-quadratic relative to a
  classic transformer at this size, so the full window is affordable next
  to a ~2.7 GiB model. Confirm actual memory behavior on real hardware
  before assuming this transfers 1:1 from the card's own description.
- This is a **rename**, not a delta pull: the old
  `Gemma4-E2B-it-qat-UD-Q4_K_XL` registration is left in place (harmless,
  unreferenced) rather than explicitly unregistered — Lemonade has no
  documented "unregister a custom model" CLI verb as of this version;
  removing the stale weights from disk, if desired, is a manual cleanup
  step outside this change's scope.

## 3. `assistant-gemma` — add the MTP draft checkpoint

```sh
lemonade pull user.Gemma4-26B-A4B-QAT-Uncensored-Balanced-Q4_K_M \
  --checkpoint main HauhauCS/Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced-MTP:Q4_K_M \
  --checkpoint draft HauhauCS/Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced-MTP:mtp-gemma-4-26B-A4B-it.gguf \
  --recipe llamacpp --label tool-calling --label mtp
lemonade load Gemma4-26B-A4B-QAT-Uncensored-Balanced-Q4_K_M \
  --llamacpp vulkan --ctx-size 262144 \
  --llamacpp-args "-np 1 -kvu --spec-type draft-mtp --spec-draft-n-max 4" \
  --save-options
```

- This re-registers the same custom model name with a second `--checkpoint
  draft <repo>:<file>` entry — confirmed against
  `lemonade-sdk/lemonade` PR #2317's `server_models.json` diff, which shows
  Lemonade's own built-in Gemma-4 MTP catalog entries using exactly this
  `checkpoints: {main, draft, mmproj}` shape (`draft` resolved via
  `model_info.resolved_path("draft")` in `llamacpp_server.cpp`, which then
  pushes `--model-draft <path>` to the underlying `llama-server` process
  automatically). Re-running `lemonade pull` under the same custom name is
  how you add a checkpoint type to an already-registered custom model —
  there is no separate "add checkpoint" verb.
- `--model-draft`, `-md`, `--spec-draft-model` are reserved by Lemonade as
  of v10.8.1 and rejected if passed through `--llamacpp-args` — do **not**
  try to pass the draft path that way; the `--checkpoint draft` flag on
  `pull` is the only supported path.
- `--spec-type draft-mtp --spec-draft-n-max 4` **are** still passed through
  `--llamacpp-args` (not on Lemonade's reserved list) — this mirrors the
  documented llama.cpp CLI pattern for MTP
  (`--spec-type draft-mtp --spec-draft-n-max <1-6>`, Unsloth's own MTP
  guide recommends starting at 2-4 and tuning per-hardware).
- `-np 1 -kvu`: **required**, not a style choice. A live community bug
  report against the merged MTP PR states plainly: `load_model: MTP
  currently supports only n_parallel=1; got 4` — resolved by setting
  `--parallel 1`. Lemonade's `-np` flag is `llama-server`'s `--parallel`
  (see `llm-lemonade` README's own concurrency section), so this alias's
  recipe must set `-np 1`, trading the 4-slot fan-out it previously had
  (per the existing `models.yaml` comment: `-np 4 -kvu`) for single-stream
  throughput. This is the real, confirmed constraint — see what.md for the
  `--mmproj` claim that did **not** hold up under the same check (moot for
  this alias either way, since it carries no `mmproj`).
- Recommended sampling per the base Gemma-4 family's own guidance (same
  pattern already used for the E2B `coder-compact` recipe): set via
  consumer defaults, not baked into the recipe.

## 4. `ornith-35b` — new custom registration (community heretic build)

```sh
lemonade pull user.Ornith-1.0-35B-uncensored-heretic-Q4_K_M \
  --checkpoint main llmfan46/Ornith-1.0-35B-uncensored-heretic-GGUF:Q4_K_M \
  --recipe llamacpp --label tool-calling
lemonade load Ornith-1.0-35B-uncensored-heretic-Q4_K_M \
  --llamacpp vulkan --ctx-size 131072 \
  --llamacpp-args "-np 4 -kvu" --save-options
```

- `ctx-size 131072` / `-np 4 -kvu`: unchanged concurrency shape from what
  this alias already runs (per `docs/agent-log.md`'s 2026-07-12 drift
  root-cause: the intended live recipe is `-np 4 -kvu`, ctx below the
  card's 262144 max) — this change swaps the weights, not the serving
  shape. Raise `--ctx-size` toward the card's 262144 max if a real workload
  needs it; not changed here to keep this a single-variable swap.
- Custom registration is new for this alias: the previous
  `Ornith-1.0-35B-GGUF-Q4_K_M` id had no `models.yaml` pull-recipe comment
  at all, implying it resolved through Lemonade's built-in catalog. The
  heretic community upload almost certainly isn't in that catalog, so this
  needs the same `user.`-prefixed custom path as `coder-agentic`/
  `assistant-gemma`/`coder-compact` — flagged as the one swap in this batch
  most likely to need a first-pull dry run before assuming the recipe
  above is exactly right (e.g. confirming the `:Q4_K_M` short-tag form
  resolves against this specific repo's file list).

## 5. `resident-small` — NPU/FLM model swap (replace, not add)

```sh
aipc models sync   # or: lemonade pull qwen3.5:4b  (FLM catalog entry, not a custom user. registration)
```

- No `user.`-prefixed custom registration and no `--checkpoint`/`--recipe`
  flags — unlike the Vulkan/llamacpp swaps above, `qwen3.5:4b` is a
  first-class FLM catalog entry on this machine (v0.9.43), pulled the same
  way `gemma4-it-e4b-FLM` already was.
- The resulting Lemonade model name is **derived, not asserted**:
  `qwen3.5-4b-FLM` (`:` → `-`, `-FLM` suffix — the same convention already
  observed for `gemma4-it:e4b` → `gemma4-it-e4b-FLM`). `tasks.md`'s
  hardware step confirms the actual generated name before
  `models.yaml`/`config.yaml` are trusted as correct against the live
  system.
- `ensure-resident-small.sh` (both `files/etc/...` and `files/usr/lib/...`
  copies) already reads the model id from `AIPC_RESIDENT_MODEL_ID` with a
  hardcoded fallback default — that default moves from
  `gemma4-it-e4b-FLM` to `qwen3.5-4b-FLM`, no logic change, no new pin
  mechanism. The existing pin-then-chat-prove loop in that script is the
  hardware verification path for "pin normal" (`tasks.md`).
- `llm-litellm`'s `resident-small` entry gains
  `extra_body.chat_template_kwargs.enable_thinking: false` (new field on
  this alias — `qwen3.5:4b` is hybrid-thinking, `gemma4-it-e4b-FLM` was
  not) — same fix already applied to `assistant-gemma`/`coder-agentic` for
  the same empty-`content`-until-`max_tokens` failure mode.
- This is a **replacement of the model behind the resident NPU slot**, not
  a second resident NPU model — `gemma4-it-e4b-FLM`'s existing entry is
  edited in place (same as how `coder-compact` and `ornith-35b` above are
  edited in place, not left alongside their predecessors).

## Verification tiers (CLAUDE.md §9)

- **Static** (this session, done): `python -c "import yaml; yaml.safe_load(...)"`
  against both `models.yaml` and the LiteLLM `config.yaml`.
- **Render** (this session, done): `tools/aipc render bootc` and
  `tools/aipc render ansible --check`.
- **Hardware** (required before any of these five are trusted as the real
  default — none of it done in this session, no hardware access): see
  `tasks.md` — pull weights, cold-load time, structured `tool_calls` through
  the LiteLLM gateway for the two tool-calling-relevant swaps
  (`coder-compact`, `ornith-35b`), an OCR/description smoke test for
  `vlm-screen`, a real decode-tok/s measurement for `assistant-gemma` with
  MTP enabled vs. the prior plain-weights baseline, and for
  `resident-small`: confirm the real `qwen3.5-4b-FLM` model name,
  `enable_thinking: false` yields clean non-empty `content`, decode/prefill
  speed is acceptable, pinning via `ensure-resident-small.sh` still works,
  and voice + mem0 + assistant-aggregator smoke tests pass against the new
  model.
