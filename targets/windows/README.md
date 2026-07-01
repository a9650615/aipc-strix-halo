# Windows one-click installer

Run this only from Windows 11 when the USB install path is unavailable. It stages the no-USB bazzite-dx path from `docs/install-windows-direct-runbook.md`: verified downloads, rEFInd, a 30 GiB `AIPC_LIVE` exFAT partition, and a rEFInd entry.

```powershell
Unblock-File .\install-windows.ps1
powershell -NoProfile -File .\install-windows.ps1
```

Preflight only:

```powershell
Unblock-File .\preflight-check.ps1
powershell -NoProfile -File .\preflight-check.ps1
```

The live payload partition is exFAT because the squashfs payload can exceed FAT32's 4 GiB single-file limit. The boot path is UNVERIFIED on Strix Halo; test it once before trusting it. Keep Windows until `aipc doctor` has been green for at least 30 days.
