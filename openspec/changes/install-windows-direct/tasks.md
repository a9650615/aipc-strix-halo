## 1. Documentation

- [x] 1.1 Add a new section to `docs/architecture.md` titled "§9 Alt: Windows-direct install (no USB)" placed between §9.4 and §9.5. Cover D1–D7 from `design.md`. Cross-reference §9.1, §9.2, §9.5, §9.6 as unchanged. (AI PC)
- [x] 1.2 Create `docs/install-windows-direct-runbook.md` — step-by-step walkthrough with screenshot placeholders, roughly 30 numbered steps grouped into Pre-flight, EFI loader setup, Disk partitioning, Boot flow, and Post-install cleanup. (AI PC)

## 2. Pre-flight artifacts

- [x] 2.1 Document the Windows pre-flight checklist in the runbook, listing accepted System Image Backup target paths (NAS, OneDrive, second internal drive). Reject USB as a target.
- [x] 2.2 Reference (do not duplicate) the BIOS settings from `docs/architecture.md` §9.2 in the runbook; this path has no BIOS changes of its own.

## 3. EFI loader setup

- [ ] 3.1 Pin a rEFInd release ≥ 0.14.0 in the runbook and document SHA-256 verification against the upstream `rod.smith` checksum file before running the installer.
- [ ] 3.2 Reference the Windows-side install script (`refind-install.bat` from the rEFInd zip); document the exact command line and elevation requirement.
- [ ] 3.3 Document the ESP layout after rEFInd install: `EFI/refind/refind_x64.efi`, `EFI/refind/refind.conf` and a `menuentry` block pointing at the bazzite-dx ISO on the 30 GB install partition.

## 4. Disk partitioning runbook

- [ ] 4.1 Document the Windows Disk Management shrink step: target 150 GB unallocated, with screenshot placeholders for the shrink dialog. Note the BitLocker-off requirement from §9.1.
- [ ] 4.2 Document the `diskpart` sequence to create a 30 GB FAT32 install partition in the unallocated region.
- [ ] 4.3 Document copying the verified bazzite-dx ISO to the install partition root.
- [ ] 4.4 Document leaving 120 GB unallocated (do NOT format it from Windows). (AI PC)

## 5. Boot flow

- [ ] 5.1 Document the reboot + rEFInd auto-detect step; user picks the bazzite-installer entry. Cover the Q1 fallback (manual `bcdedit` chainload) inline.
- [ ] 5.2 Reference `docs/architecture.md` §9.4 for the bazzite installer flow itself; document only the difference: disk selection is "install to free space" / unallocated region, NOT "use entire disk". Cover the Q2 fallback (Fedora Workstation Live ISO + later `bootc switch`) inline. (AI PC)
- [ ] 5.3 Document the post-install boot: rEFInd menu shows bazzite-dx + Windows Boot Manager; both are bootable; user verifies both at least once.

## 6. Post-install cleanup (30-day deferred)

- [ ] 6.1 **IMPLEMENTATION FUTURE**: spec only. Document the contract of `aipc disk wipe-windows` in the runbook (and reference from `docs/architecture.md` §9 Alt):
  - Interactive confirmation prompt naming the partitions to be wiped
  - Refuses to run unless `aipc doctor` is green AND at least 30 days have elapsed since install
  - Removes the Windows NTFS partition and the 30 GB FAT32 install partition
  - Auto-extends the BTRFS filesystem into the freed space
  - Exits non-zero with a single-line diagnosis on any failure
  No CLI code is written in this change.
- [ ] 6.2 Document a manual fallback in the runbook (`gparted` + `btrfs filesystem resize`) for users who want to wipe before the CLI ships.

## 7. Verification

- [ ] 7.1 Run `npx -y @fission-ai/openspec validate install-windows-direct --strict`; output must be "valid".
- [ ] 7.2 Add a cross-link from `docs/architecture.md` §9 (just under the "Install Flow" heading) to the new §9 Alt section so users on the USB path also know the alternative exists.
- [ ] 7.3 Hardware verification on the AI PC (one pass): confirm rEFInd registers on Strix Halo firmware (Q1), and confirm the bazzite-dx installer's behaviour with respect to "install alongside" vs "use entire disk" (Q2). Record findings in the runbook and, if needed, open a follow-up change. (AI PC)
