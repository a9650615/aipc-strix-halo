# What

Add a conditional user-session Bluetooth audio recovery capability to the
existing `voice-pipecat` module.

## Requirements

- Start once from the user `default.target` after PipeWire, pipewire-pulse, and
  WirePlumber are available.
- Treat a Bluetooth audio device as needing attention when it is paired and
  its expected `bluez_output.<MAC>.1` sink is absent.
- If it is merely disconnected, try one normal BlueZ connection without
  restarting audio.
- If it is half-connected, restart the user audio services, disconnect/
  reconnect the device, and, if needed, restart Bluetooth and power-cycle the
  adapter before one final reconnect attempt.
- Exit without changing state when the sink exists or the device is not
  paired.
- Bound all waits and return a non-zero status when recovery times out.
- Never delete pairings, scan forever, or restart audio unconditionally.
- Keep built-in analog as the fallback when Bluetooth is unavailable.
