# llm-lemonade

Runs AMD's Lemonade SDK to serve small models (<3B parameters) on the XDNA 2
NPU. Lower latency than iGPU for intent classification and embeddings.

## What it does

- Runs the Lemonade runtime inside a Podman quadlet with `/dev/accel` passed
  through.
- Exposes an OpenAI-compatible HTTP API on a localhost port.
- Serves `intent-3b` and `embed-bge` (see `llm-litellm` model namespace).

## Unit placement

`lemonade.service` is a plain systemd unit (not a podman quadlet), shipped
under `files/etc/systemd/system/` and placed by the renderer. No hand-install
in `post-install.sh`.

## Dependencies

- `system-unified-memory` (NPU visible via lspci, amd-xdna driver loaded).
- `system-base` (Podman).

## Consumers

Not called directly. `llm-litellm` routes NPU-eligible models here.

## Runtime requirements

- `amd-xdna` driver loaded and NPU visible via `lspci`.
- Lemonade server container image, pinned by digest in
  `files/etc/systemd/system/lemonade.service`:
  `ghcr.io/lemonade-sdk/lemonade-server@sha256:e727643d...` (= tag `v10.8.1`,
  verified against the ghcr manifest 2026-07-02). The previously referenced
  `amd/lemonade-sdk` image does not exist on Docker Hub; upstream publishes to
  ghcr via `lemonade-sdk/lemonade`'s `build-and-push-container.yml`. Bump by
  resolving a newer tag's digest and updating both the unit file and this line.
