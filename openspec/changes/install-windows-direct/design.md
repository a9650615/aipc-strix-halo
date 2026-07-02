## Decisions

### D1. rEFInd is the EFI boot manager used from the Windows side

The Windows-direct path needs an EFI loader that (a) the user can install from inside Windows without a USB stick, (b) can chainload an ISO from local disk, and (c) survives most OEM firmware quirks.

**Choice: rEFInd 0.14+.** Ships a Windows-side `refind-install.bat` that drops `refind_x64.efi` into the ESP and registers a UEFI boot entry via `bcdedit` / NVRAM. Has a stable ISO chainload story. Project is mature and well-documented.

**Alternatives considered:**
- **systemd-boot** — cleanest minimal loader, but has no Windows-side installer and assumes a Linux userspace is already present.
- **GRUB2** — heavyweight; installing it from Windows is unsupported.
- **Ventoy** — strong GUI and multi-ISO support, but introduces a third-party EFI loader chain that is harder to recover from when it misbehaves.
- **Windows Boot Manager + `bcdedit` chainload** — uses only what Windows ships, but in practice chainloading non-Windows EFI binaries via BCD is fragile across OEM firmware versions; rEFInd registers itself the same way and then takes over the menu.

### D2. Extract vmlinuz + initrd + LiveOS, not ISO chainload (REVISED during implementation)

Originally: chainload the ISO file in place via rEFInd. Revised: rEFInd's ISO chainload depends on firmware-specific El Torito handling and is unreliable, and copying the whole ISO offers no way around per-file size limits on the payload filesystem.

**Choice: extract components.** vmlinuz + initrd go to `EFI/refind/aipc/` on the ESP; the LiveOS squashfs goes to the `AIPC_LIVE` partition; the rEFInd menuentry boots the kernel with `options "root=live:LABEL=AIPC_LIVE rd.live.image quiet"`.

**Alternatives considered:**
- **Chainload the ISO directly** (original choice) — fewer steps on paper, but firmware-dependent and forces a >4 GiB single file onto the install partition.

### D3. Disk layout — 30 GB exFAT `AIPC_LIVE` partition + 120 GB unallocated for Linux (REVISED: exFAT, not FAT32)

The bazzite-dx LiveOS squashfs can exceed 4 GiB — over FAT32's single-file limit — so the payload partition is exFAT. (The ESP itself stays FAT32 as UEFI requires; it only holds the <100 MB vmlinuz/initrd.)

**Choice: two-step Windows shrink.**

1. From Windows Disk Management: shrink C: by 150 GB → leaves 150 GB unallocated.
2. From `diskpart`: create a new 30 GB primary exFAT partition labelled `AIPC_LIVE` in that unallocated region for the LiveOS payload.
3. The remaining 120 GB stays unallocated for the bazzite-dx installer to claim.

After bazzite is installed and verified, the 30 GB install partition is reclaimable.

**Alternatives considered:**
- **FAT32 payload partition** (original choice) — blocked by the 4 GiB single-file limit on the squashfs.
- **One partition** — payload and Linux fight for space, and the bazzite installer cannot safely shrink a filesystem it is also booting from.
- **Use ESP only** — typical 100–500 MB ESP cannot hold a multi-GB payload.
- **Use Windows C: directly via NTFS** — rEFInd has NTFS read support via a driver, but reliability is weaker; not worth the saved partition.

### D4. Dual-boot for 30 days, then wipe Windows

Wiping Windows in the same session as a brand-new bazzite install is high-risk: if anything goes wrong with Phase 0 verification, there is no fallback OS on the machine.

**Choice: leave Windows in place at install time.** The bazzite installer is pointed at the 120 GB unallocated region (not "use whole disk"). After install, rEFInd shows a dual-boot menu. After 30 days of verified bazzite-dx usage (the user's own judgement, gated on `aipc doctor` green), the user manually removes the Windows partition + the 30 GB install partition with `gparted` from Linux, or with the future `aipc disk wipe-windows` CLI (see Q3 below).

**Alternatives considered:**
- **Same-session wipe** — faster, smaller diff, but no rollback path if Linux setup fails.
- **Permanent dual-boot** — wastes 100+ GB on a Windows install the user does not plan to use.

### D5. Recovery without a USB — Windows Recovery Environment lives on the disk

The USB path uses the bazzite installer USB as its emergency recovery medium. The Windows-direct path cannot rely on that. WinRE, however, lives on a hidden partition on every Windows 11 install and is reachable via Shift+Restart → Troubleshoot → Advanced.

**Choice: WinRE + a System Image Backup taken in pre-flight to non-USB storage.** Pre-flight task creates a Windows System Image Backup to NAS, OneDrive, or a second internal drive. If the bootloader is bricked post-install, the user holds Shift+Restart, walks into WinRE, and restores from the backup. WinRE itself does not need a USB.

**Alternatives considered:**
- **Recommend an emergency USB** — defeats the entire premise of this change.

### D6. BIOS Secure Boot remains Disabled

Same as §9.2 of `docs/architecture.md`. rEFInd has Secure Boot support via shim, but it is an advanced setup (MOK key enrolment) and is not worth the complexity in this first cut.

**Choice: no change from §9.2.** Defer Secure Boot enablement to a later OpenSpec change.

### D7. This path is opt-in, not the default

The USB path (§9.3–§9.4) is faster, lower-risk, and has years of community documentation. The Windows-direct path is for users who cannot acquire a USB stick.

**Choice: documentation calls the Windows-direct path "alternative", points users at the USB path first, and recommends switching to it if a USB stick becomes available before the install starts.**

## Open Questions

### Q1. UEFI implementation quirks on Strix Halo

rEFInd works on the vast majority of AMI Aptio firmware, but specific OEM bugs (boot entry registration not persisting, NVRAM clearing on power loss) can force a fallback to a `bcdedit` chainload. **Action**: hardware verification step in the runbook; if rEFInd fails to register, document the `bcdedit /create /d "rEFInd" /application bootsector` fallback before declaring this path generally usable.

### Q2. Bazzite-DX installer "install alongside" support

If the bazzite installer's only disk options are "use entire disk" and manual partitioning, users will need to either use manual partitioning (acceptable but more error-prone) or boot a Fedora Workstation Live ISO instead — which DOES support installing to unallocated space — then `bootc switch` to bazzite-dx afterwards. **Action**: verify on hardware which installer flow lands cleanly; if "install alongside" is unavailable, the runbook should document the Fedora Workstation intermediate step.

### Q3. `aipc disk wipe-windows` CLI: CLI or runbook only?

A CLI that interactively wipes the Windows + 30 GB install partition and extends BTRFS into the freed space is safer than asking the user to run `gparted` and `btrfs filesystem resize` by hand. **Recommendation: ship as a CLI**, with required confirmation prompt, backup-confirmation prompt, and an `aipc doctor` precondition (must be green). **Out of scope for this change** — implementation is future work; this change only specifies the CLI's contract in the runbook and tasks.

## Risks

- **Bricked bootloader → user has no install media** → Mitigation: WinRE on disk + mandatory pre-flight System Image Backup (D5).
- **rEFInd not registering on this specific firmware** → Mitigation: bcdedit chainload fallback documented in the runbook (Q1).
- **Bazzite installer wipes Windows by accident** → Mitigation: D4's "install to unallocated space only", explicit user-side disk selection step in the runbook, no automation of disk selection.
- **30-day dual-boot soak forgotten → permanent disk waste** → Mitigation: `aipc doctor` adds a "stale Windows partition detected, day N of soak" informational note after install; not in scope to implement here, listed in tasks for the future CLI work.

## Cross-references

- `docs/architecture.md` §9.1, §9.2, §9.5, §9.6, §9.7, §9.8 are unchanged.
- `CLAUDE.md` §6 hardware assumptions hold; this path adds no new ones.
- This change does not touch `modules/`.
