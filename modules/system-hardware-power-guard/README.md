# system-hardware-power-guard

Host daemon **`aipc-power-agent`**: one process, two orthogonal power policies
sharing a poll loop (not a shared decision state machine).

| Policy | Trigger | Action |
|---|---|---|
| **backfeed** | weak AC / battery back-feed while plugged in | clamp `scaling_max_freq` + EPP; persist charge cap |
| **core_parking** | user selects PPD `power-saver` | offline half the logical CPUs (GZ302EA cores 8–15 + SMT) |

Replaces the former pair of units:

- `power-guard.service` → transitional **Alias** of `aipc-power-agent.service`
- `aipc-usbc-core-policy.service` → **absorbed** (core parking policy; no longer keys off USB-C PD)

## Why not one state machine

Triggers and actuators differ (supply emergency vs user power mode). Merging
decisions recreated the old “USB-C ⇒ park cores” footgun. Shared I/O only.

## Unit / paths

| Item | Path |
|---|---|
| Service | `aipc-power-agent.service` (Alias: `power-guard.service`) |
| Binary | `/usr/lib/aipc-power-agent/agent.py` |
| Config | `/etc/aipc/power-agent/config.yaml` |
| State | `/var/lib/aipc-power-agent/state.json` |
| Agent kill switch | `/etc/aipc/power-agent.disabled` |
| Backfeed kill switch | `/etc/aipc/power-agent/backfeed.disabled` (also legacy `/etc/aipc/power-guard.disabled`) |
| Core-parking kill switch | `/etc/aipc/power-agent/core-parking.disabled` |

## CLI

```bash
aipc power-agent enable|disable|status
aipc power-guard enable|disable|status   # same unit; legacy name
```

## Backfeed policy (detail)

When SoC draw exceeds the adapter, BAT0 back-feeds (`Discharging` while AC
online, negative `power_now`, or falling `energy_now`). Clamp frequency, then
release adaptively: EMERGENCY → RECONNECTING → EXPANDING ⇄ CAUTIONARY.

EPP is written only in EMERGENCY/RECONNECTING; once stable, tuned/powerdevil own
EPP again. `scaling_max_freq` is the hard bound this policy alone owns.

Charge cap: re-applies `charge_threshold_percent` on start (ASUS EC resets to
100 at boot before KDE runs).

## Core-parking policy (detail)

- **Authoritative:** tuned-ppd `ActiveProfile == power-saver`
- **Fallback:** ASUS `platform_profile == quiet` if PPD unavailable
- Debounced (default 2 polls × `poll_interval_s`)
- On stop / disable: restores all targeted CPUs

## Configuration

See `files/etc/aipc/power-agent/config.yaml`. Nested `backfeed:` / `core_parking:`
sections; legacy flat power-guard YAML still loads as backfeed-only defaults with
core_parking enabled.

Ships `backfeed.dry_run: true` (observe-only). Flip to `false` after a real
back-feed calibration on hardware.

## Dependencies

- `python3`, `python3-pyyaml`
- Host unit (writes sysfs) — not a container/quadlet
- Optional: `busctl` + `tuned-ppd` for PPD profile (core parking)

## Verification

- `verify.sh` — syntax, self-test (live sysfs read), unit shape
- `tools/tests/test_power_guard_charge_cap.py` — backfeed charge-cap / EPP handoff
- `tools/tests/test_power_agent_core_parking.py` — PPD-driven park/restore

## Coexistence

Does **not** manage ASUS EC `platform_profile` (that was `platform-profile-*`,
separate). Does not fight tuned for EPP outside backfeed emergencies.
