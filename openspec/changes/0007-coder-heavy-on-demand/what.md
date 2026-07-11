# What: `coder-heavy` — Qwen3-Coder-Next 80B-A3B, On-Demand With Idle Release

Add one new Lemonade-backed alias and the residency policy that makes it safe
on 128GB UMA.

## Model Choice (researched 2026-07-12)

**Qwen3-Coder-Next (80B total / 3B active), Unsloth UD-Q4_K_XL GGUF, ~46GB,
Apache 2.0, 256k context.** Ranked #1 for this box's agentic-coding use case:

- Benchmark-backed 42.7 tok/s decode on this exact hardware/backend class
  (Ryzen AI Max+ 395 128GB, llama.cpp Vulkan — fromthematrix.dev 10-model
  Strix Halo benchmark).
- Purpose-trained for tool-calling coding agents: 70.6 SWE-Bench Verified,
  roughly matching 355B-class GLM-4.7 at ~1/7 the footprint; explicitly
  tested against Claude Code / Cline scaffolds.
- Smallest footprint in its class (46GB vs gpt-oss-120b's 63GB, GLM-4.5-Air's
  60GB) → most KV headroom for long agentic contexts.

Runners-up, and why not: **gpt-oss-120b** decodes ~20% faster (52 tok/s) but
has community-documented Harmony-format tool-call leakage after ~5+
sequential tool calls in llama.cpp — exactly our main usage pattern.
**GLM-4.5-Air** has a long clean tool-call track record but is July-2025
vintage and ~22-25 tok/s; GLM-4.6/4.7-Air were never released, and the
GLM-4.7-generation local model (GLM-4.7-Flash) is only 31B-A3B.
**Nemotron 3 Super 120B-A12B** fits but measured 18-19 tok/s. **MiniMax M2.x /
GLM-5 / DeepSeek V4 / Kimi K2.6** are all far over the size budget.

## Changes

### `modules/llm-models/files/etc/aipc/models/models.yaml`

- New alias:

  ```yaml
  - alias: coder-heavy
    backend: lemonade
    model_id: Qwen3-Coder-Next-UD-Q4_K_XL
    size_gb: 46
    idle_unload_after_s: 600
  ```

  On-demand only, never pinned: lemond loads it on first inference; the 0006
  idle-release job unloads it after 10 idle minutes.

- **Residency policy (user-visible default change, flagged per CLAUDE.md
  §10):** `ornith-35b` and `assistant-gemma` gain `idle_unload_after_s: 900`.
  Rationale: Lemonade's LRU evicts by count, not bytes; steady-state must
  leave ≥ ~50GB headroom (46GB weights + KV) or loading `coder-heavy` OOMs.
  With idle release on the two occasional 35B/26B models, the steady-state
  resident set is `resident-small` (NPU, pinned) + `coder-agentic` — leaving
  ~75GB free. `coder-agentic` stays always-resident (it is the main lane and
  must not queue behind reloads).

### `modules/llm-litellm/files/etc/aipc/litellm/config.yaml`

- New entry `coder-heavy` → `openai/Qwen3-Coder-Next-UD-Q4_K_XL` on the
  lemond router (`127.0.0.1:8001`), same local-model policy as the other
  Lemonade entries (`timeout: 1800`, `num_retries: 0`).
  `model_info: max_input_tokens: 262144, max_output_tokens: 8192`.
  No `enable_thinking` override — Coder-Next is a non-thinking instruct model.

### `openspec/specs/ai-runtime/spec.md` (delta in this change's `specs/`)

- New requirement: heavy on-demand alias — loads on demand, idle-releases,
  and the steady-state fleet always leaves enough headroom to load it.

## Capability Impact

- `ai-runtime`: gains a 100B-class offline coding lane with deterministic
  release.
- `llm-models` / `llm-litellm`: one new alias each; two aliases opt into the
  existing 0006 idle policy.

## Dependencies

- Change **0006** (idle-release mechanism) must be implemented and
  hardware-verified first — this change is its second consumer.
