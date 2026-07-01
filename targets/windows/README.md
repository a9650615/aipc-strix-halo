# Windows one-click installer

Run this only from Windows 11 when the USB install path is unavailable. It stages the no-USB bazzite-dx path from `docs/install-windows-direct-runbook.md`: verified downloads, rEFInd, a 30 GiB `AIPC_LIVE` exFAT partition, and a rEFInd entry.

## Guided menu (recommended)

The repo-root `Install-AIPC-Windows.ps1` provides a keyboard-operated guided flow with journey overview, settings checklist, read-only preflight, and staged confirmation:

```powershell
Unblock-File .\Install-AIPC-Windows.ps1
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\Install-AIPC-Windows.ps1
```

Menu options: show journey, show settings, run preflight, start staging, show next steps, exit.

## Direct target script

The backend script runs all phases without the guided menu. Use only if you need to skip the menu layer:

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

The live payload partition is exFAT because the squashfs payload can exceed FAT32's 4 GiB single-file limit. The boot path is UNVERIFIED on Strix Halo; test it once before trusting it. Keep Windows until `aipc doctor` has been green for at least 30 days.
