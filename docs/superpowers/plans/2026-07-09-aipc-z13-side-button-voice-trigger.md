# AIPC Z13 Side Button Voice Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ASUS ROG Flow Z13 unused side button trigger the existing `aipc-voice-once` voice assistant path with one key press.

**Architecture:** Reuse the existing KDE hotkey helper and `aipc-voice-once` path. Map the hardware button to a normal key (`F20`) via hwdb only if KDE cannot capture it directly; add discovery tooling before committing to a real scancode.

**Tech Stack:** Python stdlib, KDE `kwriteconfig6`/`qdbus6`, systemd-hwdb, udev, existing bootc/ansible renderers, pytest.

## Global Constraints

- No hardcoded username or home path.
- Do not launch voice from udev or root system services.
- Do not run runtime actions such as `modprobe`, `udevadm`, or `systemctl` from module `post-install.sh`.
- Hardware completion requires the physical Z13 / Strix Halo side button to launch `aipc-voice-once`; static/render checks are not hardware verification.
- No evdev daemon unless KDE capture and hwdb remap both fail on real hardware.

---

## File Structure

- `modules/voice-pipecat/files/usr/bin/aipc-voice-bind-hotkey`: choose shortcut from CLI/env/config/fallback and bind it in KDE.
- `modules/voice-pipecat/files/etc/aipc/voice/hotkey`: stable default shortcut (`F20`).
- `modules/voice-pipecat/files/etc/xdg/autostart/aipc-voice-hotkey.desktop`: run the binder inside KDE login session.
- `modules/system-asus-input/files/usr/bin/aipc-asus-side-button-discover`: hardware discovery helper; no writes.
- `modules/system-asus-input/files/etc/udev/hwdb.d/90-aipc-asus-side-button.hwdb`: safe template for later real scancode mapping.
- `tools/aipc_lib/render_bootc.py` and `tools/aipc_lib/render_ansible.py`: compile/apply hwdb when rendered modules ship hwdb files.

## Task 1: Voice hotkey config and autostart

**Files:**
- Modify: `modules/voice-pipecat/files/usr/bin/aipc-voice-bind-hotkey`
- Create: `modules/voice-pipecat/files/etc/aipc/voice/hotkey`
- Create: `modules/voice-pipecat/files/etc/xdg/autostart/aipc-voice-hotkey.desktop`
- Modify: `modules/voice-pipecat/verify.sh`

**Interfaces:**
- Consumes: existing `/usr/bin/aipc-voice-once` command.
- Produces: `_choose_shortcut(cli_shortcut: str | None, config_path: Path, env: Mapping[str, str]) -> str`.

- [ ] Add `_shortcut_from_file()` and `_choose_shortcut()` to `aipc-voice-bind-hotkey`.
- [ ] Change `--shortcut` default to `None`; use `_choose_shortcut()` in `main()`.
- [ ] Extend `--self-test` to assert CLI override, env override, config-file `F20`, and fallback `Meta+Space`.
- [ ] Create `files/etc/aipc/voice/hotkey` with exactly `F20`.
- [ ] Create KDE autostart desktop file with `Exec=/usr/bin/aipc-voice-bind-hotkey` and `OnlyShowIn=KDE;`.
- [ ] Extend `modules/voice-pipecat/verify.sh` to check the config and autostart files exist.
- [ ] Run `modules/voice-pipecat/verify.sh`; expected exit `0`.

## Task 2: ASUS side-button discovery and hwdb template

**Files:**
- Create: `modules/system-asus-input/files/usr/bin/aipc-asus-side-button-discover`
- Create: `modules/system-asus-input/files/etc/udev/hwdb.d/90-aipc-asus-side-button.hwdb`
- Modify: `modules/system-asus-input/post-install.sh`
- Modify: `modules/system-asus-input/verify.sh`

**Interfaces:**
- Produces: `find_event_nodes(devices_text: str) -> list[InputDevice]` in the discovery helper.
- Produces: hwdb template target key `f20`.

- [ ] Write stdlib Python discovery helper that parses `/proc/bus/input/devices` for `Asus WMI hotkeys` and `ASUSTeK Computer Inc. GZ302EA-Keyboard`.
- [ ] Add `--self-test` with a sample `/proc/bus/input/devices` fixture.
- [ ] In normal mode, print candidate `/dev/input/eventX` nodes and tell the operator to use KDE capture first, then hwdb if `MSC_SCAN` is observed.
- [ ] Add the hwdb template without a guessed `KEYBOARD_KEY_` mapping.
- [ ] Replace `post-install.sh` with a no-op shell script.
- [ ] Fix `verify.sh` disabled path to use `$(basename "$this_dir")`.
- [ ] Extend `verify.sh` to check helper executable, hwdb template, self-test, and absence of `modprobe`/`udevadm`/`systemctl`/voice-launching in `post-install.sh`.
- [ ] Run `modules/system-asus-input/verify.sh`; expected exit `0`.

## Task 3: Renderer hwdb support

**Files:**
- Modify: `tools/aipc_lib/render_bootc.py`
- Modify: `tools/aipc_lib/render_ansible.py`
- Modify: `tools/tests/test_render_bootc.py`
- Modify: `tools/tests/test_render_ansible.py`
- Modify: `tools/tests/test_render_parity.py`

**Interfaces:**
- Produces: `_has_hwdb(mods: list[Module]) -> bool` or equivalent in each renderer.

- [ ] Add renderer detection for `files/etc/udev/hwdb.d/*.hwdb`.
- [ ] In bootc render, emit `RUN systemd-hwdb update` before `RUN bootc container lint` when hwdb exists.
- [ ] In ansible render, emit a shell task named `Update systemd hwdb` with command `systemd-hwdb update` when hwdb exists.
- [ ] Add bootc test with synthetic hwdb file; assert output contains `systemd-hwdb update`.
- [ ] Add ansible test with synthetic hwdb file; assert parsed tasks contain the shell command.
- [ ] Extend parity test so both renderers reference `systemd-hwdb update` for the same synthetic module.
- [ ] Run renderer tests; expected pass.

## Task 4: Docs and verification

**Files:**
- Modify: `modules/voice-pipecat/README.md`
- Modify: `modules/system-asus-input/README.md`
- Modify: `docs/voice-pipeline.md`
- Modify: `openspec/changes/phase-3-voice/tasks.md`

**Interfaces:**
- Documents the hardware flow: KDE capture → hwdb remap to `F20` → `aipc-voice-bind-hotkey` → `aipc-voice-once`.

- [ ] Document `F20` default and KDE autostart in `voice-pipecat` README.
- [ ] Document `aipc-asus-side-button-discover` and hwdb live-hotfix commands in `system-asus-input` README.
- [ ] Update `docs/voice-pipeline.md` hardware handoff with side-button commands.
- [ ] Update `phase-3-voice/tasks.md` to mark only static/render side-button support complete; keep hardware tasks unchecked until real button press is verified.
- [ ] Run static checks:
  ```bash
  modules/voice-pipecat/verify.sh
  modules/system-asus-input/verify.sh
  PYTHONPATH=tools pytest tools/tests/test_doctor_voice.py tools/tests/test_doctor_memory_rag.py tools/tests/test_render_bootc.py tools/tests/test_render_ansible.py tools/tests/test_render_parity.py -q
  npx -y @fission-ai/openspec validate phase-3-voice --strict
  ```
- [ ] Run render checks:
  ```bash
  PYTHONPATH=tools python -m aipc_lib.cli render bootc --image-ref localhost/aipc:side-button-ptt --build-date 2026-07-09 --out /tmp/aipc-side-button-Containerfile.generated
  PYTHONPATH=tools python -m aipc_lib.cli render ansible --out /tmp/aipc-side-button-site.generated.yml
  ```
- [ ] Confirm generated outputs include `aipc-voice-hotkey.desktop`, `aipc-asus-side-button-discover`, `90-aipc-asus-side-button.hwdb`, and `systemd-hwdb update`.

## Self-Review

- Spec coverage: all approved plan sections map to Tasks 1-4.
- Placeholder scan: no TBD/TODO placeholders; the hwdb file intentionally ships a commented template because hardware scancode is unknown until real Z13 discovery.
- Type consistency: `_choose_shortcut()` and discovery parser names are used consistently.
