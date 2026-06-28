# ai-rocm

ROCm 7 userspace stack for the gfx1151 iGPU: management tools (rocm-smi,
amd-smi) and the HIP runtime that every GPU consumer links against.

## What it does

- Adds the AMD ROCm 7 dnf repository if not already configured.
- Installs `rocm-smi`, `amd-smi`, and `rocm-hip-runtime` pinned to the
  ROCm 7 release stream.
- Provides the HIP runtime that `llm-ollama` and `llm-vllm` containers
  inherit via the host userspace.

## Dependencies

- `system-unified-memory` (GTT sizing, HSA overrides, amdgpu loaded).
- `system-base` (dnf, base OS).

## Consumers

- `llm-ollama`, `llm-vllm` (HIP runtime).
- `system-unified-memory` verify (calls `rocm-smi --showid`).
- `aipc doctor` (calls `rocm-smi` and `amd-smi`).

## Hardware assumption

AMD Ryzen AI MAX+ 395, gfx1151 iGPU, 128 GiB unified RAM. See `CLAUDE.md §6`.
