# system-unified-memory

Exposes the AMD Ryzen AI MAX+ 395 (Strix Halo) 128 GB DDR5X pool as dynamic GPU memory (GTT)
for the gfx1151 iGPU, sets HSA overrides for ROCm userspace, and carries `amdgpu` kernel
argument workarounds needed for this hardware to boot with a stable display.

## What it does

- Sets `amdgpu.gttsize=125000` kernel argument so ≥ 120 GiB of RAM appears as GTT.
- Sets `amdgpu.dcdebugmask=0x410` (`DC_DISABLE_REPLAY | DC_DISABLE_PSR`) to work around
  Panel Replay *and* Panel Self Refresh driver bugs on Strix Halo eDP panels that freeze the
  internal display (compositor commit hangs in `dmub_replay_enable`/`dmub_psr_enable` while
  the rest of the system stays responsive). Confirmed on ASUS ROG Flow Z13 (GZ302EA),
  2560x1600@180Hz panel with VRR enabled. Harmless on Strix Halo devices without a built-in
  eDP panel.
- Loads `amdgpu` with `gttsize`/`dcdebugmask` overrides via modprobe drop-in.
- Exports `HSA_OVERRIDE_GFX_VERSION=11.5.1` and `ROCm_PATH` via env drop-ins sourced by every login shell.
- Enables `gpp-wake-fix.service`, a boot-time oneshot that disables the GPP0/GPP1 PCIe
  bridges as ACPI wake sources — they fire a spurious wake interrupt immediately after
  suspend entry that hangs the kernel on this hardware. See "Known issue: sleep/suspend
  freeze" below.

## Dependencies

None (base amdgpu driver is in-kernel).

## Hardware assumption

AMD Ryzen AI MAX+ 395, gfx1151, 128 GiB unified RAM. See `CLAUDE.md §6`.

## Calibration note

`amdgpu.gttsize=125000` (MiB) is the current working value. Verify via
`dmesg | grep -i 'amdgpu.*gtt'` after first boot; adjust if the reported size
differs materially. See `design.md` Open Questions.

## Known issue: eDP freeze is only partially mitigated (check periodically)

`amdgpu.dcdebugmask=0x410` fixes both freeze signatures reproduced and root-caused on this
fleet so far (`dmub_replay_enable` and, as of 2026-07-04, `dmub_psr_enable` — both WARNING →
stuck/hung compositor commit), but it is **not a confirmed full fix**. Per
`ublue-os/bazzite#3029` (same GZ302EA hardware; closed 2025-10-20 as "completed" but kept
accumulating reports of the same symptom through at least 2026-03) and related upstream
discussion:

- Some users hit a different-looking freeze (`[drm] *ERROR* [CRTC] flip_done timed out`)
  even with Replay *and* PSR both disabled — suggesting more than one trigger path exists on
  this hardware, possibly a firmware/PCIe power-state timing issue rather than a pure kernel
  driver bug (some users report the same freeze on Windows).
- BIOS updates (this fleet ships GZ302EA.308; some upstream reporters are on `.311`) have
  anecdotally reduced frequency for some users but not eliminated it; no ASUS fix was
  confirmed as of the last upstream comment (2026-03-06).
- Newer kernels (6.19.x reported via CachyOS) anecdotally helped one user; unconfirmed as a
  general fix. This fleet is already on 7.0.9, newer than that anecdote.

2026-07-04: escalated from `0x400` to `0x410` after hardware-verifying a real
`dmub_psr_enable` WARNING (triggered by `kwin_wayland`'s `amdgpu_dm_commit_streams` →
`dc_set_psr_allow_active` path) in this fleet's own `journalctl -k` output — direct evidence
PSR, not just Replay, misbehaves on this exact machine.

**Re-check when revisiting this module:**
1. Is there a newer GZ302EA BIOS than `.308` from ASUS that claims display/power fixes?
2. Has `gitlab.freedesktop.org/drm/amd` closed with a real upstream fix? If so,
   `amdgpu.dcdebugmask=0x410` may become unnecessary.
3. If a freeze recurs on this fleet with a *different* signature than
   `dmub_replay_enable`/`dmub_psr_enable` (e.g. `flip_done timed out`), this workaround does
   not cover it — no further community-tried kernel-arg escalation is known at this point.

## Known issue: sleep/suspend freeze (GPP0/GPP1 spurious wake)

Separate from the display-freeze bugs above: this hardware only supports `s2idle` (not real
`S3` suspend), and per `ublue-os/bazzite#2988` and `#1928`, the GZ302EA has PCIe bridges that
fire a spurious wake interrupt immediately after suspend entry, hanging the kernel — a
firmware/interrupt-routing issue upstream (a bazzite maintainer, `antheas`) spent significant
effort on without finding a complete kernel-side fix; anecdotal improvement has been tied to
specific firmware/BIOS versions, not confirmed general.

Hardware-verified 2026-07-04 on this fleet's own `/proc/acpi/wakeup`: `GPP0` and `GPP1` (both
USB4 PCIe bridges, `pci:0000:00:01.1`/`.2`) show `*enabled` as S4 wake sources — matching the
exact pattern a Z13 owner reported fixing sleep/wake for them in `#1928`. `gpp-wake-fix.service`
disables both at boot (idempotent: only toggles a device that's currently `*enabled`, so
re-running it or hardware where they're already off is a no-op).

**This has not yet been confirmed to fully fix suspend on this fleet** — it removes one
specific, community-verified spurious-wake source, but the freeze-while-charging pattern
`antheas` describes may have other contributing causes on some units. Re-check by actually
suspending and resuming after `gpp-wake-fix.service` has run; if it still hangs, the next
data point to gather is whether it's charging-state-dependent (reported trigger in
`#2988`) and whether a newer BIOS than `.308` is available.
