# Bluetooth Audio Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conditional user-session recovery for the recurring LG-XT7S A2DP half-connect after reboot.

**Architecture:** A pure stdlib Python helper decides whether the paired device is missing its PipeWire sink, then tries a normal connection or performs one recovery sequence through `systemctl --user`, `busctl`, and `wpctl`. A user oneshot starts it after the existing PipeWire services; the normal path exits without restarting anything.

**Tech Stack:** Python 3 standard library, systemd user unit, BlueZ D-Bus (`busctl`), Pulse compatibility CLI (`pactl`), PipeWire CLI (`wpctl`), WirePlumber config.

## Global Constraints

- Do not delete or rewrite Bluetooth pairing state.
- Do not add dependencies or a new module category.
- Do not restart audio when the target `bluez_output` already exists or when a paired speaker is merely disconnected.
- Poll state with a bounded deadline; do not use an unbounded scan or fixed sleep-only ordering.
- Build-time `post-install.sh` only installs files and declarative symlinks; it never starts services.
- Preserve the user's unrelated dirty worktree changes.

### Task 1: Lock the recovery predicate with tests

**Files:**
- Create: `modules/voice-pipecat/tests/test_bluetooth_audio_recover.py`
- Test: the created unittest file

**Interfaces:**
- `sink_name(mac: str) -> str`
- `has_sink(pactl_output: str, mac: str) -> bool`
- `needs_recovery(*, paired: bool, connected: bool, pactl_output: str, mac: str) -> bool`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from aipc_bluetooth_audio_recover import has_sink, needs_recovery, sink_name


class BluetoothAudioRecoveryTests(unittest.TestCase):
    def test_builds_sink_name_from_mac(self):
        self.assertEqual(
            sink_name("68:52:10:35:29:44"),
            "bluez_output.68_52_10_35_29_44.1",
        )

    def test_detects_exact_pipewire_sink(self):
        output = "59697\\tbluez_output.68_52_10_35_29_44.1\\tPipeWire\\ts16le 2ch"
        self.assertTrue(has_sink(output, "68:52:10:35:29:44"))
        self.assertFalse(has_sink(output, "AA:BB:CC:DD:EE:FF"))

    def test_recovers_only_paired_connected_device_without_sink(self):
        self.assertTrue(
            needs_recovery(
                paired=True,
                connected=True,
                pactl_output="",
                mac="68:52:10:35:29:44",
            )
        )
        self.assertFalse(
            needs_recovery(
                paired=True,
                connected=False,
                pactl_output="",
                mac="68:52:10:35:29:44",
            )
        )
        self.assertFalse(
            needs_recovery(
                paired=True,
                connected=True,
                pactl_output="1\\tbluez_output.68_52_10_35_29_44.1\\tPipeWire",
                mac="68:52:10:35:29:44",
            )
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=modules/voice-pipecat/files/usr/lib/aipc-voice python3 modules/voice-pipecat/tests/test_bluetooth_audio_recover.py`

Expected: FAIL with `ModuleNotFoundError` because the recovery helper does not exist yet.

### Task 2: Implement the minimal helper and user unit

**Files:**
- Create: `modules/voice-pipecat/files/etc/aipc/aipc_bluetooth_audio_recover.py`
- Create: `modules/voice-pipecat/files/etc/aipc/aipc-bluetooth-audio-recover`
- Create: `modules/voice-pipecat/files/usr/lib/systemd/user/aipc-bluetooth-audio-recover.service`

**Interfaces:**
- The helper exposes the three pure functions from Task 1 for tests.
- The executable runs `main()` and returns 0 for no-op/success, non-zero for a failed recovery.

- [ ] **Step 1: Implement pure naming/detection functions**

```python
def sink_name(mac: str) -> str:
    return f"bluez_output.{mac.replace(':', '_')}.1"


def has_sink(pactl_output: str, mac: str) -> bool:
    target = sink_name(mac)
    return any(target == line.split("\\t")[1] for line in pactl_output.splitlines() if "\\t" in line)


def needs_recovery(*, paired: bool, connected: bool, pactl_output: str, mac: str) -> bool:
    return paired and connected and not has_sink(pactl_output, mac)
```

- [ ] **Step 2: Implement bounded BlueZ/PipeWire recovery**

The runtime path must:

1. Read `AIPC_BLUETOOTH_AUDIO_MAC`, defaulting to `68:52:10:35:29:44`.
2. Read BlueZ `Paired` and `Connected` through `busctl`.
3. Read `pactl list short sinks`; exit 0 if the target sink exists or the device is not paired+connected.
4. For a paired, disconnected device, try one direct BlueZ `Connect` and wait up to 45 seconds for the target sink.
5. For a half-connected device, restart the three user audio units, call BlueZ `Disconnect`, wait for `Connected=false`, and call `Connect`.
6. If reconnect fails, restart system Bluetooth, power-cycle the adapter, refresh the BlueZ device path, and retry once.
7. Run `wpctl set-default <sink>` only after the target sink exists; return 1 if a broken-state recovery times out.

- [ ] **Step 3: Add the user unit**

```ini
[Unit]
Description=Recover paired Bluetooth audio after a half-connect
After=pipewire.service pipewire-pulse.service wireplumber.service
Wants=pipewire.service pipewire-pulse.service wireplumber.service

[Service]
Type=oneshot
ExecStart=/usr/bin/aipc-bluetooth-audio-recover
TimeoutStartSec=60

[Install]
WantedBy=default.target
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `PYTHONPATH=modules/voice-pipecat/files/usr/lib/aipc-voice python3 modules/voice-pipecat/tests/test_bluetooth_audio_recover.py`

Expected: 3 tests pass.

### Task 3: Install durably and preserve fallback routing

**Files:**
- Modify: `modules/voice-pipecat/post-install.sh`
- Modify: `modules/voice-pipecat/verify.sh`
- Modify: `modules/voice-pipecat/README.md`
- Create: `modules/voice-pipecat/files/etc/wireplumber/wireplumber.conf.d/51-aipc-audio-routing.conf`

- [ ] **Step 1: Add executable permissions and the default-target symlink**
- [ ] **Step 2: Add the existing analog/HDMI/Bluetooth priority rules as the durable image source**
- [ ] **Step 3: Add the focused unittest to `verify.sh`**
- [ ] **Step 4: Document the conditional recovery and its no-op behavior**
- [ ] **Step 5: Run `modules/voice-pipecat/verify.sh`**

Expected: exit 0 with the existing self-tests and Bluetooth recovery tests passing.

### Task 4: Live hotfix and hardware verification

**Files:**
- Copy the new repo helper/unit/routing config to their live destinations only after diffing the current files.

- [ ] **Step 1: Copy the helper, unit, and WirePlumber config to the live machine**
- [ ] **Step 2: Run `systemctl --user daemon-reload` and enable the unit for the current user session**
- [ ] **Step 3: Run the helper in the current healthy session; expect a no-op and no audio restart**
- [ ] **Step 4: Verify `systemctl --user status aipc-bluetooth-audio-recover.service`, `wpctl status`, and the LG sink**
- [ ] **Step 5: Reboot once, then verify the service result and `bluez_output.68_52_10_35_29_44.1` without manual recovery**

### Task 5: Static/render verification and incident record

**Files:**
- Modify: `docs/agent-log.md`

- [ ] **Step 1: Run the module static verification and OpenSpec strict validation**
- [ ] **Step 2: Run bootc and ansible renders plus render-parity checks**
- [ ] **Step 3: Append the runtime incident and permanent recovery outcome to `docs/agent-log.md`**
- [ ] **Step 4: Inspect the diff and confirm unrelated dirty files were not changed**
