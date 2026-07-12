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

- **On AC + GPU sustained busy:** holds a `systemd-inhibit --what=sleep
  --mode=block` lock (refuses the suspend request outright, does not just
  delay it).
- **Otherwise (AC + GPU idle for a few polls, or on battery at all):**
  releases the lock; normal suspend proceeds through whatever triggered it.

### Threshold + hysteresis (2026-07-10)

Ambient load on this AI PC (desktop compositor + always-on Lemonade/Kokoro)
often sits at **10–30%** `gpu_busy_percent`. The original default
`BUSY_THRESHOLD=15` therefore held the sleep block almost permanently on
AC — “该释放不放”. Defaults are now:

| Env | Default | Meaning |
|---|---|---|
| `BUSY_THRESHOLD` | **50** | % busy before counting toward a lock |
| `BUSY_STREAK_NEED` | 2 | consecutive busy polls (~10s) to *acquire* |
| `IDLE_STREAK_NEED` | 3 | consecutive idle polls (~15s) to *release* |
| `POLL_INTERVAL` | 5 | seconds between polls |

Override via `Environment=` on the unit (or drop-in). Kill switch:
`/etc/aipc/suspend-gpu-guard.disabled`.

## Journald forensics drop-in (2026-07-12)

A second real hang — s2idle suspend, USB device unplugged mid-sleep, resume
never came back, forced power-cycle — showed the runtime journal for that
boot had almost nothing left except ~40k lines of `plasma-systemmonitor`
spamming a QML warning (`TreeViewDelegate.qml: Unable to assign [undefined]
to QString`) after one of its sensors vanished along with the unplugged
device. That flood evicted whatever kernel/suspend evidence existed for the
actual hang before it could be inspected.

`files/etc/systemd/journald.conf.d/90-suspend-hang-forensics.conf` raises
`RuntimeMaxUse`/`SystemMaxUse` (default was unset → small implicit cap) and
tightens `RateLimitBurst` to 1000/30s so a single runaway app can no longer
evict a whole boot's worth of real log before anyone gets to read it. This
doesn't fix the KDE-side QML bug (upstream, not this repo's to patch) — it
just makes sure the *next* hang leaves evidence behind.

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
