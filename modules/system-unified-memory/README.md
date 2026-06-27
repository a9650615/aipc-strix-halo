# system-unified-memory

Exposes the AMD Ryzen AI MAX+ 395 (Strix Halo) 128 GB DDR5X pool as dynamic GPU memory (GTT)
for the gfx1151 iGPU and sets HSA overrides for ROCm userspace.

## What it does

- Sets `amdgpu.gttsize=125000` kernel argument so ≥ 120 GiB of RAM appears as GTT.
- Loads `amdgpu` with `gttsize` override via modprobe drop-in.
- Exports `HSA_OVERRIDE_GFX_VERSION=11.5.1` and `ROCm_PATH` via env drop-ins sourced by every login shell.

## Dependencies

None (base amdgpu driver is in-kernel).

## Hardware assumption

AMD Ryzen AI MAX+ 395, gfx1151, 128 GiB unified RAM. See `CLAUDE.md §6`.

## Calibration note

`amdgpu.gttsize=125000` (MiB) is the current working value. Verify via
`dmesg | grep -i 'amdgpu.*gtt'` after first boot; adjust if the reported size
differs materially. See `design.md` Open Questions.
