## 1. Windows guided transfer

- [x] 1.1 Convert `Install-AIPC-Windows.ps1` from a thin delegate into a numbered keyboard menu: overview, preflight only, start staging, show next steps, exit.
- [x] 1.2 Keep `targets/windows/install-windows.ps1` as the staging backend; do not duplicate download, checksum, rEFInd, partition, or payload logic in the root menu.
- [x] 1.3 Add basic settings reminders before staging: BitLocker off, Secure Boot off, UEFI boot, non-USB WinRE System Image Backup completed, and Windows will not be wiped automatically.
- [x] 1.4 Preserve `-WhatIf` dry-run and all existing typed confirmations for destructive disk operations.

## 2. Linux guided bootstrap

- [x] 2.1 Convert `install-aipc-linux.sh` from a thin delegate into a simple keyboard prompt showing when it is safe to run: after vanilla Bazzite DX is installed and booted from the internal disk.
- [x] 2.2 Require acknowledgement before invoking `tools/bootstrap.sh`; preserve bootstrap's existing hardware probe, age key prompt, `bootc switch`, and reboot prompt.

## 3. Documentation

- [x] 3.1 Update `README.md` to show the guided Windows and Linux entrypoints and the install journey split: Windows stages installer → user boots/tests/installs Bazzite → Linux bootstrap runs after installed system boots.
- [x] 3.2 Update `targets/windows/README.md` to describe the guided menu and keep the direct target script documented as the lower-level backend.

## 4. Verify

- [x] 4.1 `npx -y @fission-ai/openspec validate guided-installer-tui --strict` → valid.
- [x] 4.2 `bash -n install-aipc-linux.sh` passes.
- [x] 4.3 If `pwsh` is available, parse `Install-AIPC-Windows.ps1`; if absent, report that parse validation was skipped.
- [x] 4.4 Grep-audit confirms no new `ExecutionPolicy Bypass`, no new destructive disk command outside the backend, and no plaintext-looking secret shapes.
- [x] 4.5 `cd tools && python3 -m pytest -q` remains green.
