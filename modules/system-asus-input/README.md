# system-asus-input

This module provides ASUS input-device support for the ROG Flow Z13 (GZ302EA) and similar hardware.

## Fixes

### 1. Keyboard hotplugging support

Detects when `ASUSTeK Computer Inc. GZ302EA-Keyboard` or `Asus WMI hotkeys` are added and triggers a `udevadm trigger` for the input subsystem. This addresses the case where the keyboard remains unusable if it was not present at boot.

### 2. Function key and hotkey mapping

Provides `udev` rules and an hwdb template so ASUS-specific WMI hotkeys can be recognized or remapped after discovery.

## Implementation details

- `files/etc/udev/rules.d/70-asus-keyboard.rules` handles keyboard and hotkey device re-triggering.
- `files/etc/udev/hwdb.d/90-aipc-asus-side-button.hwdb` is a template for a later `KEYBOARD_KEY_<scan>=f20` mapping once hardware discovery finds the real scan code.
- `files/usr/bin/aipc-asus-side-button-discover` helps capture the side-button event without writing system state.
- `post-install.sh` is intentionally a no-op so the module stays build-time safe on bootc and ansible renders.

## Side button discovery

Use the discovery helper on the physical AI PC:

```bash
aipc-asus-side-button-discover --timeout 20
```

Start by checking whether KDE can capture the side button directly. If KDE sees the button, bind it there and stop.

If the helper only reports `MSC_SCAN`, use that discovered scan code to fill the hwdb template with a real mapping:

```text
KEYBOARD_KEY_<scan>=f20
```

Apply the live hotfix on the running machine with:

```bash
sudo systemd-hwdb update
sudo udevadm trigger --subsystem-match=input
```

Do not claim the side button is complete until the physical button is pressed on the hardware and the end-to-end `F20` path is confirmed in a real desktop session.

### GZ302EA (2025) — 控制中心鍵 (Command Center)

Official chassis label (ASUS diagram): **控制中心**, between volume keys
and USB-A on the tablet edge (power → volume → **Command Center** → USB).

Windows behavior (ROG docs / forum): short-press opens Command Center /
ScreenXpert; long-press often launches Copilot — largely **not remappable**
in Armoury Crate.

**Linux path (hardware-verified 2026-07-10):**

InputPlumber (`50-rog_flow_z13.yaml`) claims `Asus WMI hotkeys` and maps
the 控制中心 / Armoury-style key to the virtual **Microsoft X-Box One Elite 2
pad**. User capture:

```text
Microsoft X-Box One Elite 2 pad|KEY|316|v1   # BTN_MODE (Guide / QuickAccess)
Microsoft X-Box One Elite 2 pad|KEY|304|v1   # BTN_SOUTH (A), often co-fired
```

| Component | Role |
|---|---|
| `aipc-command-center.service` | Watches Elite pad for 316/304 → `aipc-voice-once` as desktop user |
| `capability_maps.d/flw1.yaml` | Prefer map Prog1–3 → keyboard **F20** (for KDE F20 bind when delivered) |
| KRunner / Meta+A | Spotlight-style text entry (always works) |

```sh
sudo systemctl status aipc-command-center
sudo aipc-asus-side-button-discover --capture --timeout 20
journalctl -u aipc-command-center -f   # press 控制中心
```

## Hardware assumption

- ASUS ROG Flow Z13 (GZ302EA) or similar hardware using ASUS WMI drivers.
