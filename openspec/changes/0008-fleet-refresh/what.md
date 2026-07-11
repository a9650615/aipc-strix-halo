# What: Five Model Swaps + One MTP Wiring

All changes are to `modules/llm-models/files/etc/aipc/models/models.yaml` and
`modules/llm-litellm/files/etc/aipc/litellm/config.yaml`, plus the two
module READMEs. No new mechanism, no new module, no new backend.

## 1. `vlm-screen`: Qwen2.5-VL-7B → Qwen3-VL-8B-Instruct (official GGUF)

- New repo: `Qwen/Qwen3-VL-8B-Instruct-GGUF` (Apache-2.0, official Qwen
  upload, `pipeline_tag: image-text-to-text`).
- Main weights: `Qwen3VL-8B-Instruct-Q4_K_M.gguf` (verified via HF tree API:
  5,027,784,800 bytes ≈ **4.7 GiB**).
- **Fact-check correction on quant pairing**: this repo does **not** ship a
  Q4_K_M-tier `mmproj` — only `mmproj-*-F16.gguf` (1.16 GiB) and
  `mmproj-*-Q8_0.gguf` (752,289,728 bytes ≈ **0.7 GiB**). Pairing the Q4_K_M
  main weights with the Q8_0 mmproj (not F16): the vision encoder is a small
  fraction of total size, so the extra precision of F16 buys little for the
  memory it costs. Combined footprint ≈ **5.4 GiB** (up from the current
  alias's undocumented Qwen2.5-VL-7B size).
- `models.yaml` currently has **no `vlm-screen` entry at all** — it only
  exists in `llm-litellm`'s config. This is a pre-existing gap between the
  two files (CLAUDE.md §7 makes `models.yaml` the single source of truth);
  this change adds the missing entry rather than leaving the drift in
  place. Flagged in the report, not treated as a new scope item — it's the
  same edit this task already needed to make.

## 2. `coder-compact`: Gemma-4-E2B QAT → Qwen3.5-4B (Unsloth UD-Q4_K_XL)

- **Correction to the originally proposed repo id**: `unsloth/Qwen3.5-4B-Instruct-GGUF`
  does not exist. The real Unsloth repo is `unsloth/Qwen3.5-4B-GGUF`
  (verified via the HF search API against `unsloth/*Qwen3.5*` — Qwen3.5's
  dense small models ship as `<name>` / `<name>-Base`, not
  `<name>-Instruct`, unlike the 2.5/3 generations).
- Quant: `Qwen3.5-4B-UD-Q4_K_XL.gguf`, verified 2,912,109,728 bytes ≈
  **2.7 GiB** — matches the size estimate in the original research.
- Context: model card confirms **262,144 native**, extensible to 1,010,000.
  Architecture (from the card): Gated DeltaNet linear-attention blocks
  interleaved with regular gated attention (8× `DeltaNet→FFN` per 1×
  `Attention→FFN`) — the long-prefill characteristic this on-demand compact
  lane benefits from is real, not marketing.
- `llm-litellm`'s `coder-compact` entry `model_info.max_input_tokens`
  updates from `131072` to `262144` to match.
- Known ecosystem note carried into `how.md`/README: community reports say
  Ollama does not support Qwen3.5 GGUFs yet — irrelevant here since this
  machine runs Lemonade's `llamacpp` backend, not Ollama, for this alias.

## 3. `assistant-gemma`: wire the MTP draft that was already sitting there

- Draft checkpoint file confirmed via HF tree API:
  `mtp-gemma-4-26B-A4B-it.gguf` in the same
  `HauhauCS/Gemma4-26B-A4B-QAT-Uncensored-HauhauCS-Balanced-MTP` repo,
  251,937,728 bytes ≈ **0.2 GiB**. New combined `size_gb`: 15.6 → **15.8**.
- Lemonade v10.8.1 (the version already pinned in `llm-lemonade`'s unit
  file) added native `checkpoints: {main, draft, mmproj}` support for this
  exact case (`lemonade-sdk/lemonade#2317`) — the pull recipe uses a second
  `--checkpoint draft <repo>:<file>` flag, not a hand-rolled
  `--llamacpp-args --model-draft` passthrough (that flag, plus `-md` and
  `--spec-draft-model`, is reserved internally as of this release and can no
  longer be passed manually).
- **Hard constraint, confirmed**: MTP speculative decoding in llama.cpp
  currently supports only `n_parallel=1` (community bug report against the
  merged MTP PR: `load_model: MTP currently supports only n_parallel=1; got
  4`). This alias's recipe therefore moves from `-np 4 -kvu` to
  `-np 1 -kvu` — a real single-stream trade-off, recorded here and in the
  `models.yaml` comment and `llm-lemonade`'s README so it isn't silently
  "fixed" back to `-np 4` later.
- **Correction to the originally assumed constraint**: the commonly-repeated
  claim that MTP is also incompatible with `--mmproj` is **not**
  corroborated — Lemonade's own official `Gemma-4-*-MTP` catalog entries
  combine `draft` + `mmproj` + a `vision` label in the same registration
  (verified via the `lemonade-sdk/lemonade#2317` diff). This is moot for
  `assistant-gemma` regardless, since this alias is not a vision variant —
  noted so the single real constraint (`-np 1`) isn't confused with an
  imagined second one.
- Community Strix Halo benchmarks for 26B-A4B+MTP report up to ~110 tok/s;
  this was 大哥's prior research citation, not independently re-verified by
  this pass, and is exactly what `tasks.md`'s hardware step re-measures on
  this box.

## 4. `ornith-35b`: point the default at the uncensored build

- New repo: `llmfan46/Ornith-1.0-35B-uncensored-heretic-GGUF`, a Heretic
  v1.2.0 decensored quant of the same base as the currently-registered
  build (`deepreinforce-ai/Ornith-1.0-35B`). Uploader's own eval: 90% fewer
  refusals (9/100 vs 89/100) at 0.0019 KL divergence from the original — not
  independently re-benchmarked here.
- Quant: `Ornith-1.0-35B-uncensored-heretic-Q4_K_M.gguf`, verified
  21,233,604,576 bytes ≈ **19.8 GiB** (up slightly from the current 19.7).
- **Same caveat as `coder-agentic`'s HauhauCS quant** (already the pattern
  in this file for decensored builds): heretic decensoring's effect on
  tool-call reliability is **not** hardware-verified on this exact quant.
  This is not a permanent promotion — `tasks.md` includes the same
  structured-`tool_calls` + multi-turn-tool-loop re-verification this
  fleet already requires before trusting a decensored default.
- This repo is a community upload, not Lemonade's built-in catalog (unlike
  the previous official deepreinforce-ai build) — needs the same
  `user.`-prefixed custom registration pattern as `coder-agentic`/
  `assistant-gemma`, documented in the `models.yaml` comment since none
  existed for `ornith-35b` before.
- **`idle_unload_after_s: 900` written now, bridging to 0007**: change
  0007 (`coder-heavy-on-demand`, not yet implemented) already specifies
  `ornith-35b` and `assistant-gemma` should both gain
  `idle_unload_after_s: 900` as part of `coder-heavy`'s headroom policy.
  Per this task's spec, 0008 writes that field onto `ornith-35b` now (it's
  touching this alias's entry anyway) rather than waiting for 0007 to land.
  **`assistant-gemma`'s half of that same 0007 requirement is left alone**
  — out of this change's named scope; 0007 still owns it.

## 5. `resident-small`: NPU/FLM model swap, `gemma4-it-e4b-FLM` → `qwen3.5-4b-FLM` (fleet review item 6)

- **This is a same-slot replacement, not an addition.** The NPU/FLM backend
  holds exactly one large resident model; hardware-tested this session:
  `gemma4-it-e4b-FLM` + `qwen3.5:4b` loaded together fail `CREATE_HWCTX -22`
  at any context size (only a 1B-class model coexists with `e4b`). So the
  `coder-heavy` (0007) headroom argument that blocked this swap earlier in
  the same review round does not apply — see why.md item 5 for the full
  reconciliation.
- New `model_id`: **`qwen3.5-4b-FLM`** — derived, not yet hardware-confirmed.
  Lemonade's FLM naming convention observed elsewhere in this file (`:` in
  the FLM tag becomes `-`, plus a `-FLM` suffix: `gemma4-it:e4b` →
  `gemma4-it-e4b-FLM`) gives `qwen3.5:4b` → `qwen3.5-4b-FLM`. The exact
  string is only generated by `aipc models sync` / `lemonade pull` against
  the live catalog — `tasks.md` carries a hardware-only task to confirm it
  rather than trust the derivation blind.
- Catalog facts (FLM v0.9.43, this machine): `qwen3.5:4b`, min_ver 0.9.43,
  Image-Text-to-Text (vision) capable, Tool Calling: Yes, 256k context,
  Q4_1 quant. 大哥 hardware-verified it serves standalone on the NPU this
  session (chat completion returned "Hello! How").
- `size_gb`: `9.6` → `2.5` (FLM footprint estimate for a 4B Q4_1 model;
  not yet hardware-confirmed against the actual pulled artifact size —
  same caveat as the derived model-id above).
- **`enable_thinking: false` is required, not optional.** `qwen3.5:4b` is a
  hybrid-thinking model like `assistant-gemma`/`coder-agentic`. Without
  `extra_body.chat_template_kwargs.enable_thinking: false` in the
  `llm-litellm` entry, `reasoning_content` fills and `content` stays empty
  until `max_tokens` — the exact failure mode already hit and fixed for
  those two aliases. `resident-small`'s entry did not previously need this
  flag (`gemma4-it-e4b-FLM` is not a hybrid-thinking model), so this is a
  new field on this alias, not a value change to an existing one.
- Audio: architecturally moot. The voice pipeline is SenseVoice STT
  (`:9001`, independent service) → text → `/chat` (plain string `content`,
  `graphs.py:604`/`1061`) → Kokoro/CosyVoice TTS. The LLM behind
  `resident-small` never receives audio either before or after this swap;
  `gemma4-it-e4b-FLM`'s audio modality was unused dead weight. Vision is
  retained (`qwen3.5:4b` has Image-Text-to-Text).
- Explicitly excluded from this item: `qwen3.6-35b` (not bundled in this
  machine's upstream FLM catalog — parked, not pursued), any actual
  `lemonade pull`/model download/service restart/live-machine change (all
  hardware-only tasks, see `tasks.md`), and `coder-heavy`'s NPU headroom
  question (already settled as not-applicable per why.md item 5, not
  reopened here).

## Capability Impact

- `ai-runtime`: five alias definitions change identity/size; one alias
  (`assistant-gemma`) gains a documented single-stream speculative-decoding
  trade-off; `ornith-35b` gains an idle-release policy ahead of 0007;
  `resident-small` moves to a newer NPU/FLM model in the same resident slot.
- `llm-models` / `llm-litellm`: registry entries + router config updated in
  lockstep (CLAUDE.md §7 single-source-of-truth).

## Dependencies

- None on 0006/0007 for the five swaps themselves. The `idle_unload_after_s`
  field only *works* because 0006's idle-release timer already exists and
  reads it generically — no new code path.
- `assistant-gemma`'s MTP wiring depends on the Lemonade version already
  pinned in `llm-lemonade` (v10.8.1) — no image/digest bump needed, unlike
  0007's llama.cpp build-date gate for `coder-heavy`.
- `resident-small`'s swap depends on the local FLM catalog already carrying
  `qwen3.5:4b` (v0.9.43, confirmed) — no Lemonade/FLM version bump needed.
