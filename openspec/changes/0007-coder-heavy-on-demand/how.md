# How: Pull, Register, Gate On llama.cpp Version, Verify Headroom

## 0. Prerequisite — llama.cpp build gate

Qwen3-Coder-Next had two real llama.cpp bugs, both fixed upstream in
Feb 2026: a `key_gdiff` compute bug that caused output looping (fixed
2026-02-04 — and the GGUFs were re-uploaded, so weights pulled before that
date are also bad) and a tool-call parser fix (2026-02-19). Before anything
else, confirm the Lemonade container's bundled `llama-server` is a
post-2026-02-19 build; if not, bump the pinned `lemonade-server` image digest
in the module first. This is a hard gate — the failure mode is silent
garbage, not an error.

## 1. Pull + register (custom checkpoint, `user.` prefix pattern)

```sh
lemonade pull user.Qwen3-Coder-Next-UD-Q4_K_XL \
  --checkpoint main unsloth/Qwen3-Coder-Next-GGUF:UD-Q4_K_XL \
  --recipe llamacpp --label tool-calling
lemonade load Qwen3-Coder-Next-UD-Q4_K_XL \
  --llamacpp vulkan --ctx-size 262144 \
  --llamacpp-args "-np 2 -kvu" --save-options
```

- `ctx-size 262144`: Coder-Next uses hybrid attention (mostly
  linear-attention layers), so KV cost per token is far below a classic
  transformer — 256k should be affordable next to 46GB weights. If
  hardware verification shows memory pressure, fall back to 131072.
- `-np 2 -kvu`: this is a heavy single-task lane, not a fan-out lane; two
  slots covers an agent + a side query. Always pair explicit `-np` with
  `-kvu` (llm-lemonade README).
- Recommended sampling (Unsloth guide): temp 1.0, top-p 0.95, top-k 40,
  min-p 0.01. Set via consumer defaults, not baked into the recipe.

## 2. Known open issue — tool schemas with multiple optional params

ggml-org/llama.cpp#20164: Coder-Next can loop tool calls under long context
when a tool declares several *optional* parameters. Mitigation until the
upstream fix lands: agent-side tool schemas should mark parameters `required`
where feasible. Document this in the module README; do not work around it in
the gateway.

## 3. Residency / headroom

- `coder-heavy` declares `idle_unload_after_s: 600` and is never pinned —
  the 0006 idle-release job (timer already ships in `llm-lemonade`) handles
  release. No new mechanism.
- `ornith-35b` and `assistant-gemma` declare `idle_unload_after_s: 900`.
  Steady state then holds only the pinned NPU model + `coder-agentic`
  (~31GB), leaving ~75GB — comfortably above the ~50GB (weights + KV) that
  a cold `coder-heavy` load needs.
- Worst case (everything recently used, nothing yet idle-released) can still
  OOM. Accepted for v1: the window is ≤15 min and shrinks as models idle
  out. A byte-aware pre-load eviction hook is explicitly out of scope —
  propose separately if the window bites in practice.

## 4. Verification tiers (CLAUDE.md §9)

- Static: yamllint models.yaml; litellm config parses; `verify.sh` checks the
  alias exists in both files.
- Render: `tools/aipc render bootc` + `tools/aipc render ansible --check`.
- Hardware (required before enabling): cold-load time from NVMe, decode tok/s
  (expect ~40 tok/s ballpark), structured `tool_calls` over a streaming
  multi-turn tool loop through the LiteLLM gateway, idle unload observed at
  +600s, and a load-under-pressure run (fleet warm → request `coder-heavy` →
  confirm no oom-kill, models idle out, load succeeds).
