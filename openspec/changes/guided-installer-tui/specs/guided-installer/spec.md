## ADDED Requirements

### Requirement: Guided Install Journey

The repo-root install entrypoints SHALL present a keyboard-operated guided flow that shows the full install journey, the current phase, the next safe action, basic settings reminders, and which steps remain manual.

#### Scenario: Windows guide shows journey before mutation

- **WHEN** `Install-AIPC-Windows.ps1` starts from the repository root
- **THEN** it shows that the Windows side stages the installer only, that BIOS/boot test/Bazzite disk selection remain manual, and that the boot path still needs hardware verification before any destructive or boot-changing action is offered

#### Scenario: Linux guide shows post-install bootstrap scope

- **WHEN** `install-aipc-linux.sh` starts from the repository root
- **THEN** it shows that it must be run after completing the vanilla Bazzite DX install and booting into the installed system, and that it delegates to `tools/bootstrap.sh`

### Requirement: Keyboard Menu Navigation

The guided installer SHALL use a simple keyboard-first menu with numbered choices and typed confirmations, without requiring a graphical desktop or extra UI framework.

#### Scenario: User can choose read-only checks

- **WHEN** the Windows guided menu is displayed
- **THEN** the user can run read-only preflight checks without starting rEFInd installation, downloads, partition resize, formatting, or payload staging

#### Scenario: User can exit safely

- **WHEN** any guided menu is displayed
- **THEN** the user can choose an exit option that performs no additional mutation and exits 0

### Requirement: Destructive Actions Stay Gated

The guided installer SHALL preserve all existing destructive-operation gates from the Windows staging backend and SHALL NOT add a path that resizes, creates, formats, removes, or modifies partitions without an exact-plan confirmation.

#### Scenario: Windows staging requires explicit confirmation

- **WHEN** the user selects the Windows staging action from the guided menu
- **THEN** the existing staging script still prints the exact disk/partition plan and requires typed confirmation before each destructive disk operation

#### Scenario: Dry run remains available

- **WHEN** the user starts the Windows guided entrypoint with `-WhatIf`
- **THEN** destructive Windows staging operations are dry-run through the underlying `SupportsShouldProcess` behavior

### Requirement: 防呆 Preconditions

The guided installer SHALL surface blocking prerequisites as readable, actionable messages before offering risky actions.

#### Scenario: Missing Windows safety prerequisite blocks staging

- **WHEN** BitLocker is enabled, Secure Boot is enabled, firmware is not UEFI, C: cannot shrink by 150 GiB, or no non-USB WinRE System Image Backup has been acknowledged
- **THEN** the Windows guide blocks staging and prints the specific prerequisite that must be fixed

#### Scenario: Linux guide requires installed-system acknowledgement

- **WHEN** the Linux guide is about to invoke `tools/bootstrap.sh`
- **THEN** it requires the user to acknowledge that vanilla Bazzite DX is already installed and booted from the internal disk, not merely running from the live installer

### Requirement: Backend Reuse

The guided installer SHALL reuse existing backend scripts for execution and keep the menu layer responsible only for guidance, selection, and confirmation routing.

#### Scenario: Windows guide delegates to target script

- **WHEN** the user selects Windows staging
- **THEN** `Install-AIPC-Windows.ps1` invokes `targets/windows/install-windows.ps1` rather than duplicating download, checksum, disk, or rEFInd logic

#### Scenario: Linux guide delegates to bootstrap

- **WHEN** the user confirms Linux bootstrap
- **THEN** `install-aipc-linux.sh` invokes `tools/bootstrap.sh` rather than duplicating hardware probe, age key, `bootc switch`, or reboot prompt logic
