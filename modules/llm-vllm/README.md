# llm-vllm

**Superseded 2026-07-04 by `llm-lemonade`'s `vllm:rocm` backend** —
Lemonade Server bundles a gfx1151-specific vLLM 0.20.1 build and
auto-provisions real HuggingFace-format (safetensors) models from its own
registry (verified against `Qwen3.5-4B-FP16-vLLM`, not currently
registered as a model alias — see `llm-lemonade`'s README), hardware-
verified with a real chat completion. This module's own quadlet never got past
the blocker below and stays `.disabled`; no reason to solve the same
model-provisioning problem twice. See `llm-lemonade`'s README for the
working path. This module is kept around (not deleted) in case a
standalone vLLM process outside Lemonade's process supervision is ever
wanted, but there's no active plan to unblock it as long as `llm-lemonade`
covers the need.

Optional vLLM backend for on-demand large model serving. Higher memory
overhead than Ollama, better batching and throughput under concurrent load.

## What it does

- Runs vLLM inside a Podman quadlet with iGPU passthrough.
- Exposes an OpenAI-compatible HTTP API on a localhost port.
- Loaded on demand; not started by default.

## Dependencies

- `system-unified-memory` (GTT sizing, HSA overrides).
- `system-base` (Podman, ROCm userspace).

## Consumers

Not called directly. `llm-litellm` routes to vLLM when Ollama throughput is
insufficient for a given request profile.

## When to use

- Concurrent requests to a 70B-class model where Ollama's single-stream
  serving becomes a bottleneck.
- Skip this module if Ollama meets throughput requirements; it adds memory
  overhead for the vLLM scheduler.
