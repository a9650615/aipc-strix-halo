# llm-ollama

Runs the Ollama daemon as a Podman quadlet, serving local models on the
gfx1151 iGPU via ROCm 7.

## What it does

- Runs `ollama serve` inside a privileged container with `/dev/kfd` and
  `/dev/dri` passed through.
- Exposes an OpenAI-compatible HTTP API on a localhost port.
- Pre-pulls the model weights declared in the module's model manifest.

## Dependencies

- `system-unified-memory` (GTT sizing, HSA overrides).
- `system-base` (Podman, ROCm userspace).

## Consumers

Not called directly by applications. All AI consumers route through
`llm-litellm`, which forwards to Ollama by model name. See `CLAUDE.md §7`.

## Runtime requirements

- `HSA_OVERRIDE_GFX_VERSION=11.5.1` inherited from `system-unified-memory`.
- iGPU visible via `rocm-smi --showid`.
