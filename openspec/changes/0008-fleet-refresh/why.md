# Why: Four Aliases Are Behind What's Actually Available Now

The 2026-07-12 fleet review (`docs/agent-log.md`, `hw-optimize-np-drift-0007-2026-07-12`
row) researched the current state of four aliases while root-causing an
unrelated `-np` drift bug and found each one has a materially better option
sitting on Hugging Face today:

1. **`vlm-screen`** runs a community Q4_K_M re-quant of Qwen2.5-VL-7B. Qwen's
   own `Qwen3-VL-8B-Instruct-GGUF` (official repo, not a re-quant) is a
   generation newer: 32-language OCR (up from 19), native GUI-element
   grounding useful for `agent-screen-control`'s future click-target work,
   and 256k native context (extensible to 1M) vs 2.5-VL's much smaller
   window. llama.cpp gained Qwen3-VL support via `ggml-org/llama.cpp#16780`
   (opened 2025-10-27), so it has had time to mature.
2. **`coder-compact`** runs a Gemma-4-E2B QAT quant. Qwen3.5-4B is a newer
   dense/hybrid-attention model in the same size class with a **262,144**
   native context window (verified against the model card: "Context Length:
   262,144 natively and extensible up to 1,010,000 tokens") built on
   **Gated DeltaNet** (linear-attention) layers — a hybrid architecture whose
   long-prefill cost scales far better than a classic transformer's, which is
   exactly the shape this on-demand compact/compaction lane needs.
3. **`assistant-gemma`**'s HF repo already ships an MTP (multi-token
   prediction) draft checkpoint alongside the main weights
   (`mtp-gemma-4-26B-A4B-it.gguf`) that was never wired up when the alias was
   first registered ("not wired on first trial — plain Q4_K_M main weights
   only", per the existing `models.yaml` comment). Lemonade's currently
   pinned release (v10.8.1) added first-class support for exactly this in
   its llamacpp recipe ("Speculative decoding now accepts draft/MTP/EAGLE3
   checkpoints" — v10.8.1 changelog, `lemonade-sdk/lemonade#2317`), so the
   missing piece is now a config change, not a wait for tooling.
4. **`ornith-35b`** is pinned to the original (refusal-heavy) upstream
   build. The user has directed the default be pointed at a decensored
   community build of the same base model
   (`llmfan46/Ornith-1.0-35B-uncensored-heretic-GGUF`) instead, matching the
   precedent already set for `coder-agentic` (HauhauCS's decensored Qwen3.6
   quant) and `assistant-gemma` (HauhauCS's decensored Gemma-4 quant) —
   `ornith-35b` was the one alias in the fleet still on a censored build.

None of these four changes need new infrastructure: no new backend, no new
idle-release mechanism (0006 already exists), no new headroom mechanism
(0007 already proposed the `idle_unload_after_s` extension pattern for
exactly this kind of alias). They are model-registry swaps plus one MTP
wiring, gated the same way every prior swap in this fleet has been —
render-verified now, hardware-verified before being trusted as default.

## Explicitly out of scope for this change

- **A 122B-class lane.** Discussed in the same review round but not
  approved by the user; left as a `Deferred` item below for a future
  change if wanted.
- **`resident-small`'s NPU/FLM model.** Considered and rejected — the user
  wants headroom preserved for the 80B `coder-heavy` lane (0007) rather than
  spent on a resident-small upgrade.
- Any model download, `lemonade pull`/`load`, service restart, or other
  live-machine mutation. This change is the registry + proposal only; every
  pull/load/verification step is a `tasks.md` item gated on hardware-session
  access (CLAUDE.md §9).

## Deferred: 122B-class lane

A ~122B-class local model was discussed as a candidate "go big" lane in the
same review (the user previously retired `qwen35-122b-q3` for being
uncomfortable to run — see `docs/agent-log.md` 2026-07-11). Not approved
this round. If revisited, it should follow the same headroom-policy pattern
0007 established for `coder-heavy` (any large on-demand alias needs the
steady-state fleet to leave room for it) rather than inventing a new
mechanism.
