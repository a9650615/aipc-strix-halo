## ADDED Requirements

### Requirement: One-Click No-USB Install Launcher

A single elevated PowerShell entry script (`targets/windows/install-windows.ps1`) SHALL stage a no-USB bazzite-dx install from within Windows 11, performing the deterministic steps automatically (verified downloads, rEFInd install, disk partitioning, live-payload staging, boot-entry generation) and leaving only the physical steps (BIOS, one boot test, picking the installer disk) to the user. A repo-root `Install-AIPC-Windows.ps1` SHALL delegate to that script so a freshly cloned repo has an obvious Windows entrypoint. The script SHALL fail closed on any unsafe precondition, require acknowledgement that a WinRE System Image Backup exists before mutation, and SHALL NOT assert that the boot mechanism works on Strix Halo firmware.

#### Scenario: Preflight refuses on unsafe state

- **WHEN** `install-windows.ps1` is run when BitLocker is enabled on C:, OR C: cannot shrink by 150 GiB, OR firmware is not UEFI, OR Secure Boot is enabled, OR the script is not running elevated
- **THEN** it writes a one-line reason to stderr and exits non-zero before touching the disk

#### Scenario: Recovery backup acknowledgement is mandatory before mutation

- **WHEN** preflight passes but the user has not acknowledged a completed Windows System Image Backup to non-USB storage for WinRE recovery
- **THEN** the script exits non-zero before resizing or formatting any partition

#### Scenario: Downloads are SHA-256 verified before use

- **WHEN** rEFInd 0.14.0 and the bazzite-dx ISO are downloaded
- **THEN** each is SHA-256 verified (`Get-FileHash -Algorithm SHA256`) against its upstream checksum file BEFORE it is expanded/copied/executed, and any mismatch aborts the script

#### Scenario: Live payload partition is FAT32, mirroring the full installer tree

- **WHEN** the 30 GB live partition is created and the payload is staged
- **THEN** it is formatted as FAT32 (labelled `AIPC_LIVE`) and the entire Bazzite Anaconda installer tree (`images/install.img`, the `bazzite-stable/` OCI repo, `.treeinfo`) is mirrored onto it, so the kernel booted with `inst.stage2=hd:LABEL=AIPC_LIVE` resolves stage2 (no installer file exceeds FAT32's 4 GiB per-file limit; the installer initrd reliably mounts vfat)

#### Scenario: Destructive disk operations are confirmation-gated

- **WHEN** any destructive disk operation (`Resize-Partition`, `New-Partition`, `Format-Volume`, `Remove-Partition`, `Set-Partition`, or `diskpart` shrink/create) is about to run
- **THEN** the script prints its exact plan (drive and sizes) and requires an interactive confirmation before executing; `-WhatIf` dry-runs every such step

#### Scenario: Idempotent re-run

- **WHEN** `install-windows.ps1` is run again after a prior (complete or partial) run
- **THEN** it skips already-completed steps (rEFInd already registered, ≥150 GiB unallocated already present, a verified ISO already staged, `AIPC_LIVE` already formatted) and exits cleanly

#### Scenario: Boot entry flagged as needing a hardware test

- **WHEN** the rEFInd menuentry is generated
- **THEN** the script documents (in output and README) that this boot path is UNVERIFIED on Strix Halo and requires one hardware boot test; the script does NOT assert the boot succeeds

#### Scenario: Repo-root Windows entrypoint delegates to the target script

- **WHEN** `Install-AIPC-Windows.ps1` is run from the repository root in an Administrator PowerShell
- **THEN** it invokes `targets/windows/install-windows.ps1` with the provided arguments and does not duplicate installer logic

### Requirement: Linux Bootstrap Entrypoint

A repo-root Linux entry script (`install-aipc-linux.sh`) SHALL delegate to `tools/bootstrap.sh` after the user has completed the vanilla bazzite-dx install and booted into the installed Linux system.

#### Scenario: Linux entrypoint preserves bootstrap behavior

- **WHEN** `install-aipc-linux.sh` is run from the repository root on the installed vanilla bazzite-dx system
- **THEN** it executes `tools/bootstrap.sh` from the repository root and preserves that script's existing prompts, `bootc switch`, and reboot confirmation behavior

### Requirement: Read-Only Preflight Check

A separate read-only script (`targets/windows/preflight-check.ps1`) SHALL run only the preflight checks (no disk mutation), printing `OK` or a one-line failure and exiting 0 or non-zero, so the user can confirm the machine is ready before touching the disk.

#### Scenario: Preflight check does not mutate disk

- **WHEN** `preflight-check.ps1` is run on a machine that passes elevation, BitLocker, UEFI, Secure Boot, and shrink-feasibility checks
- **THEN** it prints `OK`, exits 0, and does not resize, format, create, remove, or modify any partition
