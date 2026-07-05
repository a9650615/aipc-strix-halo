# system-hardware-power-guard

Host daemon that prevents battery **back-feed drain** on weak AC adapters and
**persists the charge cap** across reboots. Runs on host (not a container) so
it can write the cpufreq/EPP/charge sysfs nodes that need root.

## What it does

1. **Back-feed clamp.** When the SoC draws more than the AC adapter supplies,
   BAT0 back-feeds the gap (`status` flips to Discharging while AC0 is online,
   or `power_now` goes negative). Sustained back-feed degrades the battery.
   The guard clamps CPU `scaling_max_freq` + amd-pstate EPP, then releases
   adaptively as the supply margin recovers (state machine:
   EMERGENCY → RECONNECTING → EXPANDING ⇄ CAUTIONARY; offline → DISCHARGING).
2. **Charge-cap persistence.** ASUS EC resets
   `charge_control_end_threshold` to 100 at boot; KDE only re-applies it after
   login. The guard re-applies `charge_threshold_percent` on boot, closing the
   reboot gap.

## Coexistence with tuned / powerdevil (no EPP fight)

`tuned` (active on this image) and KDE `powerdevil` both write amd-pstate EPP.
This guard does **not** fight them for EPP outside emergencies:

- `scaling_max_freq` (hard frequency ceiling) is the guard's alone — tuned/
  powerdevil never write it, so it is the clamp that actually bounds draw.
- EPP is written **only** in EMERGENCY/RECONNECTING (`power`). Once stable
  (EXPANDING/CAUTIONARY) and on `_release`, the guard stops touching EPP and
  lets tuned/powerdevil own it. Result: no per-poll EPP oscillation.

## Startup behavior (INIT also observes)

At daemon start (boot or restart) the adapter is unknown (could be 65W or
140W), so INIT enters RECONNECTING — it clamps to `reconnect_freq_factor` and
observes for `reconnect_observe_period_s` before expanding. Cost: a brief
throttle after every start. This is deliberate: a wrong guess here back-feeds
the battery.

## Controls (AMD Ryzen AI MAX+ 395, amd-pstate-epp)

- `scaling_max_freq` — hard frequency ceiling (fraction of `cpuinfo_max_freq`)
- `energy_performance_preference` — EPP hint (`power … performance`)
- `charge_control_end_threshold` — charge cap (%)

## Detection (both read from `/sys/class/power_supply`)

- `status == Discharging` AND `AC0 online == 1` → definite back-feed
- `power_now < drain_threshold_uw` → early numeric back-feed
- `power_now` trending down → caution (approaching the limit)

## Configuration

`/etc/aipc/power-guard/config.yaml` — all thresholds/timing are tunable.
Ships `dry_run: true` (observe-only); flip to `false` once the event log shows
correct reactions, then it actually clamps.

## Kill switch

- `/etc/aipc/power-guard.disabled` — `ConditionPathExists=!…` keeps the unit
  from autostarting; the daemon also checks it each poll and freezes (monitor-only).
- Manage via `aipc power-guard enable|disable|status`.

## Dependencies

- `python3`, `python3-pyyaml`
- Mirrors `system-memory-oom-guard`'s host-unit approach (not a quadlet).

## Verification tier

Render-verified + live-sysfs self-test. **Not hardware-verified** until a real
back-feed event is observed on the AI PC and the guard reacts correctly — see
the `.disabled` marker and CLAUDE.md §9.

## Note: the "unknown battery"

KDE may show an `ELAN… Stylus` battery with a red ✕ — that is an ELAN
touchpad/stylus HID descriptor reporting a `power_supply` with `PRESENT=0`
(`hid-0018:04F3:43C7.0003-battery`). It is harmless and `upower` already marks
it `power supply: no`; this guard only watches `BAT0`. Hiding it is a KDE
desktop setting, not a system-module concern.
