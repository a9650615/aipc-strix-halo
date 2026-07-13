# Bluetooth Audio Recovery Design

## Goal

Recover the paired LG-XT7S A2DP output after login when BlueZ reports a
connection but PipeWire has not created the corresponding `bluez_output`.
Normal audio sessions must not be restarted.

## Evidence

The recurring failure is `Connected=true` with `ServicesResolved=false`, no
PipeWire `bluez_output`, and BlueZ errors `Unable to select SEP` / `Device or
resource busy`. Restarting the user audio stack and reconnecting the device
restores A2DP. The existing WirePlumber priority rules only choose among
available sinks and cannot repair this half-connected state.

## Design

- Add a small stdlib-only recovery helper to `voice-pipecat`, the existing
  user-facing voice/audio module.
- Start it once from a user systemd unit after the PipeWire user services.
- Poll BlueZ/PipeWire state instead of using a fixed startup sleep.
- Exit without changes when the target sink already exists, or when the
  device is not paired. For a paired but disconnected device, try one normal
  connection without restarting audio.
- On the half-connected state, restart `wireplumber`, `pipewire-pulse`, and
  `pipewire`, disconnect/reconnect the known device through BlueZ, and, if the
  reconnect still fails, restart Bluetooth and power-cycle its adapter before
  one final reconnect attempt.
- Keep the existing analog/HDMI priority config as the fallback when the
  Bluetooth speaker is absent.
- Never delete pairing data, scan indefinitely, or restart audio on every boot.

## Verification

- Unit tests cover MAC-to-sink naming, `pactl` sink detection, and the exact
  recovery predicate.
- Static verification runs the stdlib test and shell/unit syntax checks.
- Render verification checks bootc and ansible outputs.
- Hardware verification confirms a reboot/login with the LG-XT7S available
  produces `bluez_output.68_52_10_35_29_44.1` without manual recovery.
