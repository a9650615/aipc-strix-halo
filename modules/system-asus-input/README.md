# system-asus-input

This module provides fixes for ASUS ROG Flow Z13 (GZ302EA) and similar hardware input issues within the OpenCode environment.

## Fixes

### 1. Keyboard Hotplugging Support
Detects when `ASUSTeK Computer Inc. GZ302EA-Keyboard` or `Asus WMI hotkeys` are connected/added to the system and triggers a `udevadm trigger` for the input subsystem. This addresses the issue where the keyboard remains unusable if not present at boot time.

### 2. Function Key / Hotkey Mapping
Provides `udev` rules to ensure that ASUS-specific WMI hotkeys are correctly recognized by the system after device addition.

## Implementation Details
- **Udev Rules**: Located in `files/etc/udev/rules.d/70-asus-keyboard.rules`.
- **Post-install**: Ensures `asus-wmi` and `input` modules are loaded via `modprobe`.

## Hardware Assumption
- ASUS ROG Flow Z13 (GZ302EA) or similar hardware using Asus WMI drivers.
