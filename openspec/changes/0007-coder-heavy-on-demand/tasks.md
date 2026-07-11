# Tasks for coder-heavy-on-demand

- [ ] 0. Gate: confirm the pinned lemonade-server image bundles a llama.cpp build ≥ 2026-02-19 (Qwen3-Next `key_gdiff` + tool-call parser fixes); bump the image digest in `modules/llm-lemonade` if older. **Blocks all other tasks.**
- [ ] 1. Pull + register `Qwen3-Coder-Next-UD-Q4_K_XL` on Lemonade (llamacpp:vulkan, ctx 262144, `-np 2 -kvu`, `--save-options`) — hardware session only.
- [ ] 2. Add `coder-heavy` alias to `modules/llm-models/files/etc/aipc/models/models.yaml` (size_gb 46, `idle_unload_after_s: 600`) with the pull/load recipe documented in the entry comment.
- [ ] 3. Add `idle_unload_after_s: 900` to `ornith-35b` and `assistant-gemma` in the same file (residency headroom policy — see what.md; user-visible default change already flagged in this proposal).
- [ ] 4. Add `coder-heavy` entry to `modules/llm-litellm/files/etc/aipc/litellm/config.yaml` (local-model timeout/num_retries policy, model_info 262144/8192).
- [ ] 5. Update `modules/llm-models/README.md` + `modules/llm-lemonade/README.md`: heavy lane, headroom policy, llama.cpp#20164 optional-params caveat for tool schemas.
- [ ] 6. Extend `modules/llm-models/verify.sh`: static check that `coder-heavy` exists in models.yaml and litellm config stays in sync.
- [ ] 7. Render verification: `tools/aipc render bootc` + `tools/aipc render ansible --check`.
- [ ] 8. Hardware verification (physical AI PC only): decode tok/s, streaming multi-turn tool_calls via LiteLLM gateway, idle unload at +600s, load-under-pressure with warm fleet (no oom-kill).
- [ ] 9. Extend `openspec/specs/ai-runtime/spec.md` from this change's delta after approval/archive.
