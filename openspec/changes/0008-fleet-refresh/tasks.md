# Tasks for fleet-refresh (0008)

## Registry + config (static, this session)

- [x] 0. Fact-check the four target repos + MTP draft filename against the
      HuggingFace API (siblings/tree, no weight download) — see what.md for
      corrections found (`unsloth/Qwen3.5-4B-GGUF`, not `-Instruct-GGUF`;
      Qwen3-VL-8B mmproj ships only F16/Q8_0, no Q4_K_M).
- [x] 1. Add the missing `vlm-screen` entry to
      `modules/llm-models/files/etc/aipc/models/models.yaml`
      (`Qwen3VL-8B-Instruct-Q4_K_M`, size_gb 5.4) with pull/load recipe
      comment.
- [x] 2. Swap `coder-compact` to `Qwen3.5-4B-UD-Q4_K_XL` (size_gb 2.7) in
      the same file; update recipe comment.
- [x] 3. Add the MTP `draft` checkpoint to `assistant-gemma`'s entry
      (size_gb 15.6 → 15.8) and its recipe comment; document the `-np 4` →
      `-np 1` trade-off inline.
- [x] 4. Swap `ornith-35b` to
      `llmfan46/Ornith-1.0-35B-uncensored-heretic-GGUF` (size_gb 19.7 →
      19.8) and add `idle_unload_after_s: 900` (bridges to 0007's plan for
      this alias — see what.md item 4).
- [x] 5. Sync `modules/llm-litellm/files/etc/aipc/litellm/config.yaml`:
      `vlm-screen` model name, `coder-compact` model name +
      `max_input_tokens: 262144`, `assistant-gemma` model name unchanged
      (same registered id, weights re-pulled underneath), `ornith-35b`
      model name.
- [x] 5b. Swap `resident-small` to `qwen3.5-4b-FLM` (derived name — see
      how.md item 5) in `models.yaml` (size_gb 9.6 → 2.5) and
      `config.yaml` (model name + required
      `extra_body.chat_template_kwargs.enable_thinking: false`); update
      `ensure-resident-small.sh` (both `files/etc/...` and
      `files/usr/lib/...` copies) default `MODEL` value, the
      `aipc-resident-small.service` Description, and `llm-lemonade`'s
      `verify.sh` grep target — **left as uncommitted working-tree edits
      per this dispatch's spec, not committed by this task.**
- [x] 6. Update `modules/llm-models/README.md` and
      `modules/llm-lemonade/README.md` with a short note on the four
      Vulkan/llamacpp swaps, the MTP single-stream trade-off, and (new)
      the `resident-small` NPU swap + its `enable_thinking: false`
      requirement.
- [x] 7. `openspec validate 0008-fleet-refresh --strict` passes.
- [x] 8. Render verification: `tools/aipc render bootc` and
      `tools/aipc render ansible --check` both exit 0.

## Hardware-only (physical Strix Halo AI PC session required — none of this run in this dispatch)

- [ ] 9. `vlm-screen`: pull + load `Qwen3VL-8B-Instruct-Q4_K_M` (main +
      Q8_0 mmproj); confirm `lemonade load` accepts the full-filename
      `--checkpoint` values from how.md without error.
- [ ] 10. `vlm-screen`: OCR/description smoke test — real screenshot
      through `agent-screen-control`'s `vlm.py` path, confirm a correct
      description is returned (same acceptance bar as the 2026-07-11
      Qwen2.5-VL-7B hardware verification this replaces).
- [ ] 11. `coder-compact`: pull + load `Qwen3.5-4B-UD-Q4_K_XL`; confirm
      cold-load time and that `--ctx-size 262144` doesn't OOM/thrash
      alongside whatever else is resident.
- [ ] 12. `coder-compact`: structured `tool_calls` + a real Hermes compact
      pass through the LiteLLM gateway (same acceptance bar as the existing
      `coder-compact` verification).
- [ ] 13. `assistant-gemma`: pull + load with the `draft` checkpoint;
      confirm `lemonade load` accepts `--checkpoint draft <repo>:<file>`
      and that `-np 1 -kvu --spec-type draft-mtp --spec-draft-n-max 4`
      loads without the `n_parallel` error this how.md's constraint is
      based on.
- [ ] 14. `assistant-gemma`: real decode tok/s with MTP enabled vs. a
      plain-weights baseline on this exact box — confirm whether the
      community "~110 tok/s" figure holds here; record the real number in
      `docs/agent-log.md` regardless of outcome.
- [ ] 15. `ornith-35b`: pull + load the heretic build; confirm the `:Q4_K_M`
      short-tag `--checkpoint main` form in how.md actually resolves
      against this repo's file list (flagged in how.md as the recipe most
      likely to need adjustment).
- [ ] 16. `ornith-35b`: structured `tool_calls` + multi-turn tool loop
      re-verification on the decensored quant (same bar already applied to
      `coder-agentic`'s HauhauCS swap) — only after this passes does the
      swap stop being "not a permanent promotion."
- [ ] 17. `ornith-35b`: confirm `idle_unload_after_s: 900` is honored by the
      existing 0006 idle-release timer for this alias (same check 0007
      itself will need for its half of this same field).
- [ ] 20. `resident-small`: `aipc models sync` (or `lemonade pull
      qwen3.5:4b`) against the live FLM catalog; confirm the actual
      generated Lemonade model name matches the derived `qwen3.5-4b-FLM`
      used in `models.yaml`/`config.yaml` — if it differs, correct both
      files to the real value before trusting this swap.
- [ ] 21. `resident-small`: confirm `enable_thinking: false` yields a
      clean, non-empty `content` response through the LiteLLM gateway
      (not `reasoning_content` filled to `max_tokens` with empty
      `content` — the known hybrid-thinking failure mode).
- [ ] 22. `resident-small`: measure NPU decode/prefill speed for
      `qwen3.5-4b-FLM` and confirm it's acceptable for the always-on
      resident chat path (compare qualitatively against the prior
      `gemma4-it-e4b-FLM` baseline); record the number in
      `docs/agent-log.md` regardless of outcome.
- [ ] 23. `resident-small`: confirm `ensure-resident-small.sh`'s pin path
      (`/api/v1/load` with `"pinned": true`, falling back to `/api/v0/load`
      / `/internal/pin`) still succeeds against `qwen3.5-4b-FLM` and that
      LRU does not evict it under load, same as the existing
      `gemma4-it-e4b-FLM` hardware verification this replaces.
- [ ] 24. `resident-small`: smoke-test voice (SenseVoice STT → `/chat` →
      Kokoro/CosyVoice TTS), `mem0`, and `assistant-aggregator` end to end
      against the new model — all three are `resident-small` alias
      consumers per CLAUDE.md §7 and should be transparent to this swap,
      but none of them have been hardware-exercised against
      `qwen3.5-4b-FLM` yet.

## Follow-on (not this change)

- [ ] 18. Extend `openspec/specs/ai-runtime/spec.md` from this change's
      delta after approval/archive.
- [ ] 19. 0007 (`coder-heavy-on-demand`) still owns adding
      `idle_unload_after_s: 900` to `assistant-gemma` and the `coder-heavy`
      alias itself — unaffected by this change.
