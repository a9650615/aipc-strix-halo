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

## Known issue: eDP freeze is only partially mitigated (check periodically)

`amdgpu.dcdebugmask=0x400` fixes the specific freeze we reproduced and root-caused
(`dmub_replay_enable` WARNING → stuck compositor commit), but it is **not a confirmed full
fix**. Per `ublue-os/bazzite#3029` (same GZ302EA hardware, tracked 2025-08 through
2026-03, still open) and related upstream discussion:

- Some users hit a different-looking freeze (`[drm] *ERROR* [CRTC] flip_done timed out`)
  even with Replay *and* PSR both disabled (`amdgpu.dcdebugmask=0x410`) — suggesting more
  than one trigger path exists on this hardware, possibly a firmware/PCIe power-state timing
  issue rather than a pure kernel driver bug (some users report the same freeze on Windows).
- BIOS updates (this fleet ships GZ302EA.308) have anecdotally reduced frequency for some
  users but not eliminated it; no ASUS fix was confirmed as of 2026-03.
- Newer kernels (6.19.x reported via CachyOS) anecdotally helped one user; unconfirmed as a
  general fix.

**Re-check when revisiting this module:**
1. Is there a newer GZ302EA BIOS than `.308` from ASUS that claims display/power fixes?
2. Has `ublue-os/bazzite#3029` or upstream `gitlab.freedesktop.org/drm/amd` closed with a
   real fix? If so, `amdgpu.dcdebugmask=0x400` may become unnecessary.
3. If a freeze recurs on this fleet with a *different* signature than `dmub_replay_enable`
   (e.g. `flip_done timed out`), the current workaround does not cover it — escalating to
   `amdgpu.dcdebugmask=0x410` is the next community-tried step, but is reported unreliable too.
