# Windows one-click installer

Two install paths are available from Windows 11:

| Path | When to use |
|------|-------------|
| **USB SSD** (recommended) | You have a USB SSD or large USB stick available |
| **No-USB** | No USB drive available; stages installer from Windows directly |

The no-USB path stages the bazzite-dx installer from `docs/install-windows-direct-runbook.md`: verified downloads, rEFInd, a 30 GiB `AIPC_LIVE` exFAT partition, and a rEFInd entry.

## Guided menu (recommended)

The repo-root `Install-AIPC-Windows.ps1` provides a keyboard-operated guided flow:

```powershell
Unblock-File .\Install-AIPC-Windows.ps1
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\Install-AIPC-Windows.ps1
```

Menu options:
- Show install journey overview (both paths)
- Show basic settings checklist (BitLocker, Secure Boot, UEFI, disk space)
- Run read-only preflight checks
- Start NO-USB staging (internal disk, destructive)
- Start USB SSD staging (external disk)
- Show next steps after staging
- Exit

## USB SSD path

Select an external USB/ATA disk from the guided menu. The script:
1. Lists detected external disks (USB or ATA bus)
2. Creates two partitions from the disk's free space (existing data untouched):
   - 1 GiB FAT32 `AIPC_ESP` — UEFI firmware requires FAT32 to boot
   - 35 GiB exFAT `AIPC_LIVE` — holds the LiveOS squashfs (can exceed FAT32's 4 GiB limit)
3. Downloads and SHA-256 verifies the Bazzite ISO
4. Stages boot files + vmlinuz/initrd to the ESP, LiveOS to `AIPC_LIVE`
5. Prints next steps: eject, plug into target machine, F12/F1 boot, install Bazzite to internal disk

The USB SSD needs at least 36 GiB of free space. Both partitions are carved from unallocated space so your existing data is preserved.

## No-USB direct target script

The backend script runs all no-USB phases without the guided menu. Use only if you need to skip the menu layer:

```powershell
Unblock-File .\install-windows.ps1
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\install-windows.ps1
```

## Preflight only

Read-only checks (elevation, BitLocker, UEFI, Secure Boot, disk space):

```powershell
Unblock-File .\preflight-check.ps1
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\preflight-check.ps1
```

## Failure recovery

Both paths log all phases with timestamps to `%ProgramData%\aipc-windows-installer\install.log`. On failure, a summary shows:
- Which phases completed successfully
- Which phase failed
- Specific recovery hints per phase (preflight, refind, shrink, partition, payload, menuentry)
- Log file location

All phases are idempotent — retrying skips completed work. Cached downloads are reused if checksum still matches.

The live payload partition is exFAT because the squashfs payload can exceed FAT32's 4 GiB single-file limit. The boot path is UNVERIFIED on Strix Halo; test it once before trusting it. Keep Windows until `aipc doctor` has been green for at least 30 days.
