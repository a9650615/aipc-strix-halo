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

**Linux detection (hardware-verified 2026-07-10 on this machine):**  
Multiple exclusive captures (with and without InputPlumber grabbing
`Asus WMI hotkeys`, plus N-KEY hidraw, gpio-keys, virtual Xbox pad) showed
**zero** KEY/MSC/HID/ACPI events when the 控制中心 key was pressed.
Stock Bazzite InputPlumber maps `KeyProg3` → gamepad QuickAccess *if*
that key ever appears; override under
`files/etc/inputplumber/capability_maps/flw1.yaml` remaps Prog1–3 → **F20**
once the kernel reports codes.

Until the kernel/firmware path exists, use:

| Path | How |
|---|---|
| KRunner Spotlight | `Alt+Space` then `aipc …` / `助理 …` (`aipc voice krunner-install`) |
| Meta+A | Opens KRunner prefilled with `aipc ` |
| F20 (software) | KDE shortcut for AIPC Voice Assistant (控制中心 does not emit F20 yet) |
| Voice energy wake | `aipc-voice-wake.service` |

```sh
sudo aipc-asus-side-button-discover --capture --timeout 20   # press 控制中心 during window
```

## Hardware assumption

- ASUS ROG Flow Z13 (GZ302EA) or similar hardware using ASUS WMI drivers.
