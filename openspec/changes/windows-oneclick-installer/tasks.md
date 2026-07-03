# Tasks — windows-oneclick-installer

## 1. Launcher scripts (`targets/windows/`)

- [x] 1.1 `install-windows.ps1` — elevated one-click. `#Requires -RunAsAdministrator`,
  `[CmdletBinding(SupportsShouldProcess)]`. Phases: preflight guard (elevated,
  BitLocker off, UEFI, Secure Boot off, C: can shrink by 150 GiB) → WinRE System
  Image Backup acknowledgement → verified rEFInd download+checksum+install →
  verified bazzite ISO+CHECKSUM download → confirmed C: shrink (150 GiB
  unallocated) → confirmed 30 GiB **FAT32** `AIPC_LIVE` partition + full
  installer-tree staging → `vmlinuz`+`initrd` to ESP + rEFInd menuentry
  (`inst.stage2=hd:LABEL=AIPC_LIVE`) → print next steps (no auto-reboot). Every
  phase idempotent; Q1/Q2 fallbacks as comments; "UNVERIFIED on Strix Halo"
  warning printed.
- [x] 1.2 `preflight-check.ps1` — read-only. Phase-1 checks only: elevation,
  BitLocker off, UEFI, Secure Boot off, and C: can shrink by 150 GiB; print `OK` /
  one-line failure; exit 0 / non-zero.
- [x] 1.3 `README.md` — why this exists, the FAT32 payload decision, the
  unverified-boot caveat, root usage
  (`Unblock-File .\Install-AIPC-Windows.ps1`; `powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\Install-AIPC-Windows.ps1`); cross-ref
  `docs/install-windows-direct-runbook.md`.
- [x] 1.4 Repo-root `Install-AIPC-Windows.ps1` delegates to `targets/windows/install-windows.ps1`.
- [x] 1.5 Repo-root `install-aipc-linux.sh` delegates to `tools/bootstrap.sh` after the vanilla bazzite-dx install is complete and the installed Linux system has booted.

## 2. Verify

- [x] 2.1 `npx -y @fission-ai/openspec validate windows-oneclick-installer --strict`
  → "valid".
- [x] 2.2 If `pwsh` available: `ParseFile` on `install-windows.ps1` → no parse
  errors. (`pwsh` absent locally; skipped and reported.)
- [x] 2.3 Grep-audit: every `Resize-Partition|New-Partition|Format-Volume|Remove-Partition|Set-Partition|diskpart`
  has a `Read-Host`/`ShouldProcess` confirm in the same phase; `Get-FileHash` +
  compare appears before first `Expand-Archive` and before ISO copy; live
  partition uses `-FileSystem FAT32` (Anaconda initrd reads vfat; no file
  > 4 GiB); no secret shapes; no auto-wipe of the Windows partition.
- [x] 2.4 `cd tools && python -m pytest -q` → still green (no Python added).

## Constraints

- Do NOT reboot the machine or wipe the Windows partition — out of scope.
- Use FAT32 for the live payload (Anaconda initrd reads vfat; no installer file > 4 GiB) — not exFAT.
- Do NOT run any destructive disk op without a confirmation gate.
- Do NOT use any download before SHA-256 verification.
- Do NOT modify existing modules, `tools/`, or the `install-windows-direct` change.
- Do NOT claim the boot mechanism works — mark it needs-hardware-verification.
- §5 no secrets; §8 terse; §11 trailer mandatory (`Agent-Orchestrator: claude-opus-4-8`).
