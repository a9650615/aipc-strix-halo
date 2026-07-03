# system-unified-memory

Exposes the AMD Ryzen AI MAX+ 395 (Strix Halo) 128 GB DDR5X pool as dynamic GPU memory (GTT)
for the gfx1151 iGPU, sets HSA overrides for ROCm userspace, and carries `amdgpu` kernel
argument workarounds needed for this hardware to boot with a stable display.

## What it does

- Sets `amdgpu.gttsize=125000` kernel argument so ≥ 120 GiB of RAM appears as GTT.
- Sets `amdgpu.dcdebugmask=0x400` (`DC_DISABLE_REPLAY`) to work around a Panel Replay
  driver bug on Strix Halo eDP panels that freezes the internal display (compositor commit
  hangs in `dmub_replay_enable` while the rest of the system stays responsive). Confirmed on
  ASUS ROG Flow Z13 (GZ302EA), 2560x1600@180Hz panel with VRR enabled. Harmless on Strix Halo
  devices without a built-in eDP panel.
- Loads `amdgpu` with `gttsize`/`dcdebugmask` overrides via modprobe drop-in.
- Exports `HSA_OVERRIDE_GFX_VERSION=11.5.1` and `ROCm_PATH` via env drop-ins sourced by every login shell.

## Dependencies

None (base amdgpu driver is in-kernel).

## Hardware assumption

AMD Ryzen AI MAX+ 395, gfx1151, 128 GiB unified RAM. See `CLAUDE.md §6`.

## Calibration note

`amdgpu.gttsize=125000` (MiB) is the current working value. Verify via
`dmesg | grep -i 'amdgpu.*gtt'` after first boot; adjust if the reported size
differs materially. See `design.md` Open Questions.
