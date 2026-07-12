# What: Gateway Memory Scheduler (Admission Control) + `coder-122b` Exclusive Alias

Add a memory-budget- and priority-aware scheduler at the LiteLLM gateway, and
register `coder-122b` as the first "exclusive"-class model that exercises it.

## New alias

- `coder-122b` — `SC117/Qwen3.5-122B-A10B-Uncensored-APEX-Compact-GGUF`
  (main 55.1 GiB + mmproj f16 0.8 GiB) on Lemonade llamacpp:vulkan. Hybrid
  thinking (litellm sets `enable_thinking: false` for tool/coding consumers,
  same as `coder-agentic`). `idle_unload_after_s: 600`.

## Manifest schema additions (models.yaml)

- `tier: exclusive | resident | floating` (default `floating`) — scheduling
  priority class. `resident-small` (NPU/FLM) is outside the GPU pool and gets
  `pool: npu` so the scheduler ignores it.
- 0011's steady-state set (`qwythos-9b`, `assistant-gemma`, `coder-agentic`)
  is marked `tier: resident`; `ornith-35b` and VLMs stay `floating`;
  `coder-122b` is `tier: exclusive`.

## Scheduler behaviour (litellm pre-call hook)

For every chat request whose target is a local Lemonade GPU model:

1. Target already loaded → pass through (fast path, no lock).
2. Otherwise compute fit against a configured GPU memory budget
   (`budget_gb`, default 96) using manifest `size_gb` + live health.
3. Doesn't fit → evict by priority: floating (LRU first) → resident →
   never an in-use model, never a model loaded less than `cooldown_s`
   (default 120) ago unless the requester is exclusive-tier. Residents are
   evicted only for an exclusive-tier target.
4. Still doesn't fit (victims busy) → **hold the request** (async wait +
   re-check) instead of forwarding — lemond never queues a load it cannot
   satisfy. Hold has a deadline; on timeout return 503 with a clear message.
5. Admission decisions are serialized (single async lock) so concurrent
   requests cannot interleave evictions — the wedged-queue round-robin
   becomes structurally impossible at the gateway.

## Idle release + resident restore (idle-release daemon extension)

- `coder-122b` idle-releases via the existing mechanism (600 s).
- New: when no exclusive-tier model is loaded and a `tier: resident` model is
  not loaded, the daemon re-warms it (POST load), restoring the agent set
  after a 122B session ends — 用完自動釋放、恢復 agent 保留.

## Capability Impact

- `ai-runtime`: new exclusive model class; gateway admission control replaces
  blind lemond load queueing for all local GPU models; resident set self-heals
  after exclusive sessions.
