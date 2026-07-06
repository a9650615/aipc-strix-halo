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
- Enables `platform-profile-auto.service` + a udev rule + a systemd-sleep hook that switch
  the ASUS EC `platform_profile` (`quiet`/`balanced`/`performance`) automatically:
  `performance` on AC power (full burst available), `quiet` on battery, reapplied on every
  plug/unplug event and after resume. Exception: `balanced`, not `performance`, while
  `llm-ollama`'s `llama-server` is actively running an inference request — see below.
- Enables `platform-profile-idle-check.timer`, which runs every 60s and — only while on
  AC — drops to `quiet` after 5 consecutive idle checks (~5 min of low CPU load + low GPU
  busy%), snapping straight back to `performance` on the very next check that sees load.
  Mac-style "quiet at idle, full burst on demand" even while plugged in. Also instantly
  forces `quiet` (ahead of every other rule) if the battery is actually discharging while
  AC is online — i.e. the current draw exceeds what this charger can supply. See "Known
  issue: idle power draw" and "Known issue: battery drains under a weak charger" below.
- Enables `gpu-hang-watch.service`, a 5s-poll journal watcher that captures a diagnostic
  snapshot (kernel + full journal, amdgpu devcoredump if present, power/GPU state) to
  `/var/log/aipc/gpu-hang/<timestamp>/` the moment the resume-from-s2idle hang signature
  appears — before the desktop goes fully unresponsive. See "Known issue:
  resume-from-s2idle amdgpu/SMU hang" below.

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

SELinux (targeted policy, enforcing) denies this by default: a plain root systemd service runs
as `init_t`, which has no `write` permission on `proc_t` (confirmed via `ausearch -m avc` showing
`denied { write }` for `gpp-wake-fix` against `/proc/acpi/wakeup`). `selinux/gpp_wake_fix.te`
grants exactly that one permission (nothing broader — an earlier attempt at using
`SELinuxContext=unconfined_service_t` in the unit instead was rejected too, since
`unconfined_service_t` also lacks `entrypoint` on the script's `etc_t` label; scoping the fix to
the actual denied operation avoids stacking more permission problems). The compiled
`gpp_wake_fix.pp` ships at `files/usr/share/selinux/packages/`; `post-install.sh` loads it via
`semodule -i` at build time (policy-store-only, no live kernel/enforcement needed). Regenerate
the `.pp` from the `.te` source with `checkmodule -M -m -o x.mod x.te && semodule_package -o
x.pp -m x.mod` if the rule ever needs to change.

**This has not yet been confirmed to fully fix suspend on this fleet** — it removes one
specific, community-verified spurious-wake source, but the freeze-while-charging pattern
`antheas` describes may have other contributing causes on some units. Re-check by actually
suspending and resuming after `gpp-wake-fix.service` has run; if it still hangs, the next
data point to gather is whether it's charging-state-dependent (reported trigger in
`#2988`) and whether a newer BIOS than `.308` is available.

## Known issue: resume-from-s2idle amdgpu/SMU hang (separate from the GPP0/GPP1 issue above)

Distinct from the "sleep/suspend freeze" above (that one hangs at suspend *entry* via a
spurious PCIe wake interrupt; this one hangs on *resume*, after suspend/resume otherwise
completed cleanly) — `gpp-wake-fix.service` being active does not prevent this.

Hit 3 times so far on this fleet (2026-07-05 x2, 2026-07-06): system resumes from `s2idle`
normally (`PM: suspend exit`, `System returned from sleep operation 'suspend'`), then
`amdgpu` starts failing SMU communication within ~30-90s — `SMU: No response msg_reg: 32
resp_reg: 0`, `Failed to retrieve enabled ppfeatures!`, `Failed to disable gfxoff!` —
escalating to a full GPU hang: `ring gfx_0.0.0 timeout`, `GPU reset begin!`, then every
recovery path fails in sequence (`MES failed to respond to msg=RESET` → `failed to reset
legacy queue` → `reset via MES failed and try pipe reset -110` → `Ring gfx_0.0.0 reset
failed`), `kwin_wayland` loses its GL context repeatedly, the desktop goes fully
unresponsive (power-key presses logged but nothing happens), and the machine needs a hard
power-off. 2026-07-06's occurrence happened with the GPU confirmed idle at suspend time
(user closed the lid after unplugging AC, no active GPU job) — ruling out "only happens
under compute load" as a precondition.

This matches an open, unresolved-upstream class of Strix Halo (gfx1151) bug, not something
fixable from this repo: `ROCm/ROCm#5590` ("amdgpu compute wave store and resume causing MES
failures"), `#5724` (MES firmware causing GPU hang / memory access fault), `#6165` (silent
hard hang under sustained load, hangcheck never fires) are all still open as of this
writing. `linux-firmware` on this fleet is `20260519` — recent, but no confirmed fixed
release is known for this specific failure signature.

**Mitigation attempted, not a confirmed fix**: added `amdgpu.cwsr_enable=0` (disables
Compute Wave Store/Resume — the mechanism the ROCm#5590 thread ties to this exact MES
failure class) alongside the existing `gttsize`/`dcdebugmask` kargs. Per the same and
related upstream threads, this is explicitly **not guaranteed** — some reporters found
disabling CWSR doesn't fix their case ("correlation not causation"), and disabling it also
means the GPU can no longer preempt mid-wave during a compute job, a real (if narrow)
functional regression risk for anything relying on shader preemption. Direct user decision
2026-07-06: try it anyway and report back after real-world use, since no better option
exists today (deep/S3 sleep isn't available on this hardware — `/sys/power/mem_sleep` only
lists `[s2idle]` — so switching sleep modes isn't on the table either).

`gpu-hang-watch.service` (5s journal poll, see "What it does" above) captures a diagnostic
snapshot to `/var/log/aipc/gpu-hang/<timestamp>/` (kernel + full journal, amdgpu devcoredump
if still present, power/GPU state, one JSON line per event in `events.jsonl`) the moment the
hang signature appears — so the next occurrence doesn't need a live session manually
grepping journalctl by wall-clock time the way this entry's own investigation did. Doesn't
prevent or fix the hang, just makes the post-mortem faster.

**Re-check when revisiting this module:**
1. Check `/var/log/aipc/gpu-hang/events.jsonl` for new entries — did
   `amdgpu.cwsr_enable=0` actually reduce/eliminate recurrences after real use? Record
   the outcome here either way — this entry should not stay "attempted, unconfirmed"
   forever.
2. Has `ROCm/ROCm#5590`/`#5724`/`#6165` (or their eventual duplicates) closed with a real
   upstream firmware/kernel fix? If so, re-evaluate whether `cwsr_enable=0` is still needed
   at all, and whether its functional downside (no compute-wave preemption) is worth
   removing once a real fix lands.
3. If a hang recurs *even with* `cwsr_enable=0`, that's a data point that this workaround
   doesn't apply to this fleet's specific trigger — don't keep re-trying the same knob:
   the next thing to check is whether it's coincident with lid-close specifically (as
   opposed to idle-timeout or manual suspend) and whether disabling lid-close-triggers-
   suspend (behavioral change, not a kernel fix) is the only remaining lever.

## Known issue: idle power draw / thermals — AC vs battery power profile

Hardware-verified 2026-07-04: with the default ASUS EC `platform_profile=balanced`, this
fleet idles at ~27-30W package power (`rocm-smi --showpower`) with typical light desktop
background load. Switching to `platform_profile=quiet` (same official ASUS `asus_wmi` +
AMD `amd_pmf` mechanism Windows Armoury Crate/Adrenalin use for their power-mode slider —
not a reverse-engineered SMU tool) drops the same load to a stable ~15-16W, plus visibly
lower fan RPM and ~5°C lower `Tctl`, with no stability risk (this is a vendor-supported EC
knob, unlike `ryzenadj`/`power_dpm_force_performance_level` which are NOT to be touched
without explicit user confirmation — see agent memory).

`platform-profile-auto.service` (+ `90-platform-profile-auto.rules` +
`system-sleep/platform-profile-resume`) applies `performance` while on AC power and
`quiet` on battery, re-evaluated instantly on every AC plug/unplug event and reapplied
after suspend/resume (the EC can reset `platform_profile` across a sleep cycle).

`platform-profile-idle-check.timer` layers a second, slower-reacting check on top of that,
active only while on AC: every 60s it reads `/proc/loadavg` (1-min load, threshold 1.00)
and `gpu_busy_percent`; 5 consecutive idle-looking checks (~5 min) drop the profile to
`quiet`, but any single check that sees load resets the counter and snaps straight back to
`performance` — asymmetric on purpose, slow to go quiet, instant to go loud, so bursty
interactive work (games, compiles) is never throttled. Counter lives in
`/run/aipc/platform-profile-idle-count` (tmpfs, naturally resets on reboot).

**Exception, direct user spec 2026-07-04**: LLM inference is a sustained GPU-bound load,
not a bursty interactive one — letting the EC chase max clocks for it just makes the
machine noticeably hotter for no perceptible latency win, which the user judged not worth
it. Both scripts detect `llm-ollama`'s `llama-server` process (`pgrep -x llama-server`)
and force `platform_profile=balanced` instead of `performance` whenever it's running (and
the idle-check treats it as never-idle, so it can't drop further to `quiet` either).
Everything else that spikes load (games, compiles) still gets full `performance` as
before. Hardware-verified: triggering both scripts while an actual inference request was
in flight (`llama-server` resident) flipped the EC from `performance` to `balanced`.

## Known issue: battery drains under a weak/travel charger despite being "plugged in"

Direct user report 2026-07-04, confirmed in use with a smaller/travel USB-C PD charger or
power bank (≤65W): this hardware's combined SoC package power alone can hit 60W+ under
real load (e.g. LLM inference), and total system draw (+ display, SSD, Wi-Fi, USB) easily
exceeds what a charger that size can supply. When that happens the battery has to
supplement the shortfall, so it visibly drains even though `AC0/online` reports 1 — this
is a real power budget ceiling, not a bug in the charge-threshold logic (`platform_profile`
itself doesn't limit charger *input* current, only the SoC's own draw).

Exact charger wattage isn't reliably readable from sysfs on this platform — `ucsi_acpi`
doesn't expose the negotiated PDO list here (`/sys/class/typec/port*/usb_power_delivery/`
is empty), so there's no clean way to compare "charger max" against "current draw" in
software. Instead, `platform-profile-idle-check` watches the one signal that's true
regardless of which charger is plugged in: `BAT0/status == "Discharging"` while
`AC0/online == 1` means whatever profile is currently active draws more than this charger
can supply, right now. That instantly forces `platform_profile=quiet` — ahead of every
other rule, including the LLM-inference `balanced` exception, since a charger too weak for
`performance` can't be assumed to handle `balanced` either. Self-corrects on the next check
once the charger can keep up again (e.g. after the burst finishes or the load lightens).

Direct follow-up, same day: "插著充電器就盡可能不去用到電池電" (avoid drawing from the
battery as much as possible while plugged in) — the 60s timer alone means up to a minute
of real drain before this guard reacts. `90-platform-profile-auto.rules` now also fires
`platform-profile-idle-check.service` on every `BAT0` `change` uevent (the kernel emits one
the moment the battery driver reports a new status), not just every 60s. This is as close
to instant as the hardware's own status reporting allows — there's no separate EC/kernel
toggle on this platform to hard-block battery discharge outright (and there probably
shouldn't be one: if AC momentarily can't cover a spike, the alternative to a brief battery
assist is a brownout/crash, not "using less power out of nowhere").

Hardware-verified: with the wrapper's `BAT_STATUS_PATH` pointed at a fake `"Discharging"`
file (battery itself was actually charging at the time), the script forced `quiet`; the
real script confirmed a no-op against real `Charging` status. `udevadm test --action=change`
confirmed the new rule resolves `SYSTEMD_WANTS=platform-profile-idle-check.service` for
`BAT0`, and `udevadm trigger --action=change` on the real device fired the real service
end-to-end (completed in <1s). Real end-to-end reproduction of an actual drain event under
the reported travel charger was not directly captured — the underlying job is
charger-agnostic by design, so it isn't expected to need per-charger tuning, but flag it if
`quiet` still isn't enough headroom for a given charger + workload combination.

The actual fix, not a software one: use the higher-wattage charger this hardware ships
with (or any charger ≥100W) for sustained heavy workloads if avoiding *any* battery draw
matters — no software profile switch can make a charger supply more watts than it has.

CPU core-parking (offlining unused logical CPUs) was considered and rejected: `cpuidle`
already uses `acpi_idle` with C1/C2/C3 all enabled and C3 (deepest) is the most-hit state
in practice on this fleet, so idle cores already draw near-zero power without the
hotplug-latency risk of reactively taking cores on/offline. SMT stays on for the same
reason — it isn't a meaningful static-idle-power cost, and halving thread count would hurt
burst workloads (LLM inference) for no real idle-power gain.

`ryzenadj` was evaluated as a finer-grained alternative (true undervolt/power-limit
control) but rejected for now: it requires either the unsigned out-of-tree `ryzen_smu`
kernel module or `iomem=relaxed` (a security-loosening kernel arg) to get past "Unable to
get memory access", and even then it pokes reverse-engineered SMU registers on a very new
(Strix Halo) platform — same risk class as forcing GPU clocks, not attempted without
explicit confirmation.
