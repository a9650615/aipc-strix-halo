# ai-rocm

ROCm 7 userspace stack for the gfx1151 iGPU: management tools (rocm-smi,
amd-smi) and the HIP runtime that every GPU consumer links against.

## What it does

- Ships `/etc/yum.repos.d/rocm.repo` as a static file (declarative; no
  build-time `curl`).
- Installs `rocm-smi`, `amd-smi`, and `rocm-hip-runtime` from that repo via
  `rpm-ostree install` in `post-install.sh`. (Cannot go in `packages.txt`:
  the aggregated install at the top of the rendered Containerfile runs
  before per-module `files/` is copied in, so the repo isn't yet
  resolvable.)
- Provides the HIP runtime that `llm-ollama` and `llm-vllm` containers
  inherit via the host userspace.

## Dependencies

- `system-unified-memory` (GTT sizing, HSA overrides, amdgpu loaded).
- `system-base` (base OS, rpm-ostree).

## Consumers

- `llm-ollama`, `llm-vllm` (HIP runtime).
- `system-unified-memory` verify (calls `rocm-smi --showid`).
- `aipc doctor` (calls `rocm-smi` and `amd-smi`).

## Hardware assumption

AMD Ryzen AI MAX+ 395, gfx1151 iGPU, 128 GiB unified RAM. See `CLAUDE.md §6`.

## Status

`.disabled` until an AI PC validates: (1) the `rocm.repo` baseurl + GPG key
at `https://repo.radeon.com/rocm/rhel9/7.0/main` resolve against the bazzite-dx
base, (2) `rpm-ostree install` of `rocm-hip-runtime` succeeds offline-cached,
and (3) `rocm-smi --showproductname` reports `gfx1151` at runtime.
