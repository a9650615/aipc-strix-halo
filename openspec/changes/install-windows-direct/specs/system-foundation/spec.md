## MODIFIED Requirements

### Requirement: Bootstrap From Vanilla bazzite-dx

`tools/bootstrap.sh` SHALL probe hardware, collect the user's age public key, and `bootc switch` a vanilla bazzite-dx host to the chosen aipc tag, with a reboot prompt. The host SHALL reach the "vanilla bazzite-dx booted" prerequisite state via EITHER of two documented paths:

- **R6a USB Live path** (existing): a USB stick is written from another machine (typically the user's Mac) per `docs/architecture.md` §9.3 and the bazzite-dx installer is booted from USB per §9.4.
- **R6b Windows-direct path** (alternative, no USB required): rEFInd is installed from a running Windows 11 host into the ESP, a bazzite-dx ISO is dropped onto a 30 GB FAT32 install partition carved from unallocated space, rEFInd chainloads the ISO at next boot, and the bazzite-dx installer is pointed at the remaining unallocated space (≥120 GB).

Both paths SHALL converge on the same vanilla bazzite-dx host state before `tools/bootstrap.sh` runs. The R6b path SHALL leave Windows bootable via the rEFInd menu until the user explicitly wipes it.

#### Scenario: Aborts on wrong hardware

- **WHEN** `tools/bootstrap.sh` runs on a host whose iGPU is not Strix Halo or whose RAM is < 120 GiB
- **THEN** it writes a one-line diagnostic to stderr and exits non-zero before invoking `bootc switch`

#### Scenario: Successful first run

- **WHEN** `tools/bootstrap.sh` runs on a fresh vanilla bazzite-dx host with valid input
- **THEN** `/etc/aipc/age.pub` is written, `bootc switch ghcr.io/<user>/aipc:<tag>` is invoked, and the host reboots into the aipc image

#### Scenario: Idempotent re-run

- **WHEN** `tools/bootstrap.sh` runs a second time with the same chosen tag on a host already running that tag
- **THEN** the script exits 0 without invoking `bootc switch` again

#### Scenario: R6b is documented for no-USB installs

- **WHEN** a user has Windows 11, ≥150 GB of unallocated NVMe space, UEFI firmware, and no USB stick available
- **THEN** `docs/architecture.md` §9 Alt and `docs/install-windows-direct-runbook.md` describe an install path that does not require a USB stick at any step

#### Scenario: R6b install failure leaves Windows bootable

- **WHEN** the bazzite-dx installer launched via R6b fails or is aborted before completion
- **THEN** the user can reboot, select "Windows Boot Manager" from the rEFInd menu, and return to a functioning Windows 11 desktop

#### Scenario: R6b successful install yields dual-boot menu

- **WHEN** the bazzite-dx installer launched via R6b completes successfully and the host reboots
- **THEN** the rEFInd menu shows at least two entries — "bazzite-dx" and "Windows Boot Manager" — and the user can boot either

## ADDED Requirements

### Requirement: Windows Recovery Path For R6b

When a user installs via the R6b Windows-direct path, the documented recovery mechanism for a bricked bootloader SHALL be the on-disk Windows Recovery Environment (WinRE) plus a System Image Backup taken before the install. The user SHALL be required, as a pre-flight step, to create a Windows System Image Backup to non-USB storage (NAS, OneDrive, second internal drive, or any other non-removable medium). No USB stick SHALL be required at any point in the R6b recovery path.

#### Scenario: Pre-flight backup step is mandated

- **WHEN** a user reads `docs/install-windows-direct-runbook.md` before starting the install
- **THEN** the runbook lists "create a Windows System Image Backup to non-USB storage" as a mandatory pre-flight step with explicit non-USB target examples

#### Scenario: Bricked bootloader recovery uses WinRE only

- **WHEN** the R6b install corrupts the boot manager such that neither bazzite-dx nor Windows boots normally
- **THEN** the user can hold Shift while clicking Restart from the Windows lock screen (or trigger WinRE via three failed boot attempts), reach Troubleshoot → Advanced → System Image Recovery, and restore Windows from the pre-flight System Image Backup without inserting any USB media

#### Scenario: Day-30 Windows wipe is deferred and reversible until executed

- **WHEN** the user has just completed the R6b install
- **THEN** the Windows partition and the 30 GB install partition both remain on disk and bootable, and the `docs/install-windows-direct-runbook.md` post-install section explicitly instructs the user to wait until `aipc doctor` has been green for ≥30 days before wiping
