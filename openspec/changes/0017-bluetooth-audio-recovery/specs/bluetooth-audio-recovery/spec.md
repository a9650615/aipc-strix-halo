## ADDED Requirements

### Requirement: Paired Bluetooth Audio Recovers After A2DP Half-Connect

The user audio session SHALL recover a paired Bluetooth audio device whose
BlueZ connection exists but whose expected PipeWire `bluez_output.<MAC>.1`
sink is absent. Recovery SHALL be bounded and SHALL not delete pairing data.

#### Scenario: Healthy Bluetooth sink is left alone

- **WHEN** the paired device has a matching `bluez_output.<MAC>.1` sink
- **THEN** the recovery unit exits successfully without restarting PipeWire,
  WirePlumber, or Bluetooth

#### Scenario: Paired speaker is disconnected at login

- **WHEN** the paired device has no sink and is not connected
- **THEN** the recovery unit tries one normal BlueZ connection without
  restarting the user audio services, and makes the sink default if it appears

#### Scenario: Half-connected speaker is repaired

- **WHEN** BlueZ reports the device paired and connected but no matching sink
  exists
- **THEN** the recovery unit restarts the user audio services, disconnects and
  reconnects the device, and sets the matching sink as default after it appears

#### Scenario: Adapter fallback clears a stale connection

- **WHEN** the reconnect still fails after the user audio restart
- **THEN** the recovery unit restarts Bluetooth, power-cycles the owning
  adapter, refreshes the device path, and retries the connection once

#### Scenario: Bluetooth remains unavailable

- **WHEN** the speaker is powered off, unreachable, or the bounded recovery
  deadline expires
- **THEN** the unit does not delete pairing data, leaves the built-in analog
  fallback available, and exits without an unbounded retry loop
