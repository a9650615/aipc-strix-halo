## Context

**SUPERSEDED 2026-07-05 (see notes inline below):** this design targeted a
single always-resident `main-70b` served by Ollama. That model was cut from
`models.yaml` in a 2026-07-04 manifest trim before Phase 1 shipped, and the
two models that actually matter now (`coder-agentic`, `ornith-35b`) migrated
from Ollama to Lemonade's `llamacpp:vulkan` backend on 2026-07-05
(hardware-verified: 35-51% faster than Ollama for identical GGUF weights; see
`modules/llm-lemonade/README.md`). Kept in place rather than rewritten
wholesale — this document was never archived, so it's fair game to correct,
but the original reasoning trail is left visible per repo convention (see
`models.yaml`'s own comments for the same pattern) rather than deleted.

The AMD Ryzen AI MAX+ 395 has two inference-capable silicon blocks: an RDNA 4
iGPU (Radeon 8060S, gfx1151) and an XDNA 2 NPU. Both share the 128 GB unified
DDR5X pool. The original goal was to keep a single 70B main-brain model
resident in GTT at all times (Mac-like fluidity), while routing
small/latency-sensitive intents to the NPU and lazy-loading specialist models
only when explicitly requested. **As actually shipped:** there is no single
pinned 70B; instead `coder-agentic` (16.9 GB) and `ornith-35b` (19.7 GB) both
stay resident simultaneously via Lemonade's `max_loaded_models: 2`, and
`resident-small` runs on the NPU via Lemonade's FLM backend.

All seven modules are containerised Podman quadlets. No host package installs
beyond what Phase 0 (`ai-rocm`, `ai-xdna`) puts in the image layer.

## Goals / Non-Goals

**Goals:**

- LiteLLM gateway is the only LLM endpoint address consumers need to know.
- NPU handles routing/intent models; iGPU handles main-70B and vision; vLLM
  handles high-throughput or batched workloads on demand.
- `main-70b` stays resident. All other models evict after 10 min idle.
- `aipc models sync` makes weight management reproducible.
- `aipc doctor` proves end-to-end liveness, not just service-active.

**Non-Goals:**

- Performance tuning beyond KEEP_ALIVE and GTT sizing — deferred to Phase 7
  (`ops-power`).
- Secure Boot re-enablement — deferred to a separate OpenSpec change.
- Multi-GPU or discrete GPU support — hardware assumption not met (CLAUDE.md §6).
- Remote or cloud-routed inference — all traffic stays on `127.0.0.1`.
- Dynamic model loading at spec time for models not in `models.yaml`.

## Decisions

**D1 — LiteLLM gateway is non-negotiable as the single endpoint**

*Chosen:* All AI consumers call `http://127.0.0.1:4000` (OpenAI-compatible).
The gateway owns routing, observability, and rate limiting.

*Alternatives:*
- Direct Ollama (11434) calls from each consumer: cheap at first, but breaks
  as soon as any backend changes port, is replaced, or needs rate limiting.
  Every consumer then becomes a maintenance surface.
- Separate gateway per capability (NPU gateway, iGPU gateway): doubles the
  port sprawl and forces callers to route themselves.

*Why rejected:* CLAUDE.md §7 makes this a project-wide constraint, not a design
preference. One gateway, one address.

**D2 — Lemonade SDK for NPU inference**

*Chosen:* `amd/lemonade-sdk` container, serving ONNX models via `/v1`-like API
on port 8001.

*Alternatives:*
- ONNX Runtime directly on host: no container isolation; more complex quadlet.
- llama.cpp with XDNA backend: XDNA MLIR backend exists but is pre-production
  as of 2026; Lemonade is AMD's supported path.
- Skip NPU for now: wastes the always-on, <2W NPU compute for wake-word and
  intent classification; forces those workloads onto iGPU, competing with 70B.

*Why rejected:* Lemonade is the only production-ready SDK for XDNA 2 on Linux
in 2026; alternatives are either unsupported or contradict the NPU-for-small
constraint from architecture.md §6.

**D3 — Ollama (not llama.cpp direct) for iGPU main inference [SUPERSEDED 2026-07-05]**

*Chosen:* `ollama/ollama:rocm` container, port 11434, with HSA_OVERRIDE_GFX_VERSION
pinned to 11.0.0 for gfx1151.

*Alternatives:*
- llama.cpp `server` binary direct: faster iteration, but manual model
  management, no built-in model server API, no keep-alive semantics.
- vLLM for the main model too: vLLM's memory management is better for
  concurrent request batching, but its startup cost (~60 s cold start) is
  unacceptable for a permanently-resident 70B model.

*Why rejected:* Ollama's model-pinning (`OLLAMA_KEEP_ALIVE=-1`) and
GGUF-native format make it the best match for a single always-resident large
model. The OpenAI-compat API it exposes plugs directly into LiteLLM.

*SUPERSEDED:* Ollama was the real initial choice through most of Phase 1, but
`coder-agentic`/`ornith-35b` migrated wholesale to Lemonade's `llamacpp:vulkan`
backend on 2026-07-05 — llama.cpp direct after all, just via Lemonade's own
`lemond` router (spawns/swaps `llama-server` child processes per model) rather
than as a bare binary, which resolves the original "no keep-alive semantics"
objection since Lemonade owns its own `max_loaded_models`/config persistence.
Hardware-measured: Vulkan beat Ollama by 35-51% on identical GGUF weights, and
ROCm (tried first, matching AMD's own guidance for this chip) was rejected on
measurement — 9.4 tok/s vs Vulkan's 38.6-58.6 tok/s, ~4x slower, despite being
the "officially recommended" backend. `llm-ollama` stays installed/enabled
(idle, not retired) in case a future model needs it. See
`modules/llm-lemonade/README.md`'s "Backend choice: Vulkan, not ROCm" section
for the full writeup.

**D4 — vLLM is on-demand, not always-on**

*Chosen:* `vllm.service` is disabled by default. LiteLLM lazy-loads it only
when a request targets one of its registered model names; the service is evicted
after 10 min of zero traffic.

*Alternatives:*
- Always-on vLLM alongside Ollama: two large models resident simultaneously
  would exhaust GTT on a 128 GB pool with a 70B model pinned.
- Replace Ollama with vLLM entirely: vLLM's throughput advantage is wasted on
  single-user, conversational workloads; its cold-start cost is a regression.

*Why rejected:* Unified memory is large but not infinite. The always-on budget
is allocated to main-70B via Ollama; vLLM earns GTT only when actively serving.

**D5 — Models live on BTRFS subvolume bind-mounted at `/var/lib/aipc-models`**

*Inherited from Phase 0 (architecture.md Q8c):* Model weights are never baked
into the image. The BTRFS subvolume layout was chosen in Phase 0 so image
updates never touch weights; snapshots capture model state independently of
the OS layer.

**D6 — Idle eviction: `main-70b` pinned, specialists evict after 10 min [SUPERSEDED 2026-07-05]**

*Chosen:* `OLLAMA_KEEP_ALIVE=-1` in `llm-ollama` quadlet keeps main-70B loaded
indefinitely. LiteLLM's `idle_timeout` parameter (or equivalent) triggers
eviction of vLLM, coder-strong, VLM, and other specialist backends after 10 min
of zero traffic (architecture.md §12 risk row: "Idle memory drift").

*Alternatives:*
- Evict everything: defeats the "Mac-like fluidity" goal; 70B cold-start is
  ~30 s, unacceptable for a conversational assistant.
- Never evict: specialists hold GTT until reboot; user would notice degraded
  performance when multiple specialists are loaded concurrently.

*SUPERSEDED:* There is no `main-70b` (cut from `models.yaml` 2026-07-04).
Residency for `coder-agentic` + `ornith-35b` is now Lemonade's own concern:
`config.json`'s `max_loaded_models: 2` keeps both loaded simultaneously
(Lemonade's own default of 1 would otherwise evict one when the other loads —
fixed via `modules/llm-lemonade/files/usr/lib/aipc/llm-lemonade/configure-lemonade.sh`).
No 10-minute idle-eviction timer exists for these two; `system-memory-oom-guard`
(a separate, later module) handles memory-pressure-triggered unloading instead
of a fixed idle timer.

## Risks / Trade-offs

- **Lemonade SDK container image schema**: The `models.yaml` field names in
  `llm-lemonade/files/` are placeholders marked TODO. Risk: schema mismatch on
  first real hardware run. **Mitigation**: task 1.3 validates on hardware before
  Phase 1 is considered done.
- **ROCm / XDNA evolving weekly**: Driver and SDK pins can break on next month's
  upstream update. **Mitigation**: monthly review window tied to `:stable`
  promotion cadence; rollback via GRUB previous deployment.
- **vLLM lazy-load startup latency**: First request after idle eviction pays a
  ~60 s cold-start. **Mitigation**: acceptable; vLLM is not used for latency-
  sensitive voice paths.
- **OLLAMA_KEEP_ALIVE=-1 and OOM**: If a specialist model is loaded concurrently
  with the pinned 70B, GTT pressure increases. **Mitigation**: LiteLLM
  concurrency limits per backend; eviction of specialists at 10 min.

## Migration Plan

No prior inference stack exists; this is a net-new layer. The only migration
concern is consumers that previously called Ollama or Lemonade directly during
Phase 0 testing. Any such scripts MUST be updated to call `http://127.0.0.1:4000`
before Phase 2 work begins. No data migration required; model weights are
downloaded fresh via `aipc models sync`.

## Open Questions

- **Lemonade SDK container image tag**: `amd/lemonade-sdk:latest` is used in
  the placeholder quadlet. A pinned digest should replace it once the image
  stabilises (tracked in task 1.2).
- **LiteLLM `idle_timeout` wiring for vLLM**: The mechanism for LiteLLM to
  stop the vLLM container after 10 min idle is not yet implemented. Task 4.2
  covers this; the exact LiteLLM config key needs validation against the version
  pinned in `llm-litellm`.
- **Model bake-off result**: Phase 0 was supposed to choose between Hermes-3-70B
  and Qwen2.5-72B-Instruct. If the bake-off has not concluded, `models.yaml`
  should list both and let the user set a default via `aipc init`.
