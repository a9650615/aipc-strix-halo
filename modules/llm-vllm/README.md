# llm-vllm

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
