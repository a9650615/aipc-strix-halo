# system-suspend-gpu-guard

Blocks suspend while the amdgpu compute queue is busy — but only on AC.
On battery, GPU busy-ness never blocks sleep; the system's own idle
timeout/lid-close/manual suspend is left free to run normally.

## Why

On this Strix Halo (gfx1151), resuming from s2idle while a GPU compute job
(e.g. llama-server) is in flight has hung the machine solid — screen stays
on, no response, no journal entries after `PM: suspend entry (s2idle)` — on
2026-07-05. An earlier resume that same day already showed the same class of
fault (`comp_1.0.1 ring timeout` on resume, recovered only because the
amdgpu ring-reset happened to succeed).

That's the AC case: prefer letting the job finish over risking a hang.
On battery the priority flips — a stuck or long-running GPU job should never
keep the machine from sleeping and draining the battery, so busy-ness is
ignored there. This guard only ever *adds* a block; it never needs to force
sleep itself — the system's own suspend triggers (idle timeout, lid close,
manual) already exist and just work once this guard gets out of the way.

## What it does

Polls `gpu_busy_percent` under `/sys/class/drm/card*/device/` and
`/sys/class/power_supply/AC0/online` every 5s.

- **On AC + GPU busy:** holds a `systemd-inhibit --what=sleep --mode=block`
  lock (refuses the suspend request outright, does not just delay it).
- **Otherwise (AC + GPU idle, or on battery at all):** releases the lock;
  normal suspend proceeds through whatever triggered it.

## Hardware assumption

AMD Ryzen AI MAX+ 395 (gfx1151), amdgpu driver exposing `gpu_busy_percent`.
See CLAUDE.md §6.

## Verification note (CLAUDE.md §9)

Render-verified + the AC-busy-detection/inhibitor-lock mechanism has been
live-checked on the physical AI PC (lock appears in `systemd-inhibit --list`
while GPU is busy on AC, disappears when idle or on battery — the battery
path verified against a faked `AC0/online` since real GPU busy-ness is
already ambient on this box). **Not** verified: a real suspend attempt while
the lock is held — deliberately, per the same risk this module exists to
avoid (see `docs/agent-log.md`, task #10 history). First real suspend it
blocks is the hardware verification for that specific claim.
