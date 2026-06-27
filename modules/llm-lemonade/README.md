# llm-lemonade

Runs AMD's Lemonade SDK to serve small models (<3B parameters) on the XDNA 2
NPU. Lower latency than iGPU for intent classification and embeddings.

## What it does

- Runs the Lemonade runtime inside a Podman quadlet with `/dev/accel` passed
  through.
- Exposes an OpenAI-compatible HTTP API on a localhost port.
- Serves `intent-3b` and `embed-bge` (see `llm-litellm` model namespace).

## Dependencies

- `system-unified-memory` (NPU visible via lspci, amd-xdna driver loaded).
- `system-base` (Podman).

## Consumers

Not called directly. `llm-litellm` routes NPU-eligible models here.

## Runtime requirements

- `amd-xdna` driver loaded and NPU visible via `lspci`.
- Lemonade SDK container image (version pinned in Containerfile, not yet written).
