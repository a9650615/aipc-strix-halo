# Windows-Direct Install Runbook (No USB Required)

This runbook documents an alternative install path that boots the bazzite-dx installer directly from the machine's own NVMe via an EFI boot manager dropped into the ESP from Windows. Use this path ONLY if you cannot acquire a USB stick.

**Prerequisites:**
- Windows 11 installed and booting
- UEFI firmware (not Legacy/CSM)
- ≥150 GB of unallocated NVMe space
- No USB stick available

**Time estimate:** ~2 hours (same as USB path)

**Risk assessment:** Higher risk than USB path — bootloader corruption requires WinRE recovery. If a USB stick becomes available before starting, switch to the USB path (§9.3–§9.4 in architecture.md).

---

## Pre-Flight

### 1. Create Windows System Image Backup (MANDATORY)

**This step is NOT optional.** Without a USB recovery stick, WinRE + System Image Backup is your only recovery path if the bootloader is bricked.

**Accepted backup targets (non-USB only):**
- NAS (network-attached storage)
- OneDrive (cloud backup, requires sufficient space)
- Second internal drive (D:, E:, etc.)

**Rejected targets:**
- USB stick (defeats the purpose of this path)
- Same C: drive you're about to shrink

**Steps:**

```
[ ] Open Control Panel → System and Security → Backup and Restore (Windows 7)
[ ] Click "Create a system image" in the left pane
[ ] Choose a destination (NAS, OneDrive, or second internal drive)
[ ] Confirm backup selection (system reserved, C:, recovery partition)
[ ] Click "Start backup" → wait 30-60 minutes
[ ] Verify the backup completed successfully
[ ] Record the backup location and date
```

**[SCREENSHOT PLACEHOLDER: System Image Backup dialog showing destination selection]**

**[SCREENSHOT PLACEHOLDER: Backup progress dialog]**

**[SCREENSHOT PLACEHOLDER: Backup completion confirmation]**

### 2. Windows Pre-Flight (from §9.1, unchanged)

```
[ ] Sign out of Microsoft account (Settings → Accounts → Your info → Sign out)
[ ] Back up BitLocker recovery key from account.microsoft.com/devices
[ ] Back up any Windows-only data to external drive or NAS
[ ] Export browser bookmarks and passwords (if not in cloud)
[ ] Save Steam library list
[ ] Record Windows OEM product key:
    PowerShell: (Get-WmiObject -query 'select * from SoftwareLicensingService').OA3xOriginalProductKey
[ ] Note current BIOS version and firmware build
[ ] Confirm the machine has no vendor-locked recovery partition
[ ] Disable BitLocker on the system drive (Settings → Privacy → Device encryption → Off)
```

### 3. BIOS Settings (from §9.2, NO changes)

**The Windows-direct path does NOT change any BIOS settings from §9.2.** Ensure:

```
[ ] CPU / RAM: EXPO/DOCP enabled, Smart Access Memory enabled
[ ] Integrated Graphics: UMA Frame Buffer Size = minimum (512 MB or 1 GB)
[ ] Security: Secure Boot = Disabled (same as §9.2)
[ ] Boot: UEFI only (no CSM/Legacy)
[ ] Save and exit if any changes were needed
```

---

## EFI Loader Setup

### 4. Download and Verify rEFInd

**Pinned release:** rEFInd 0.14.0 or later

**Steps:**

```
[ ] Download rEFInd from SourceForge:
    https://sourceforge.net/projects/refind/files/0.14.0/
    File: refind-bin-0.14.0.zip (or later)
[ ] Download the SHA-256 checksum file from the same page:
    File: refind-bin-0.14.0.zip.txt (or later)
[ ] Verify the ZIP against the checksum:
    certutil -hashfile refind-bin-0.14.0.zip SHA256 > downloaded.txt
    Compare downloaded.txt with refind-bin-0.14.0.zip.txt
[ ] If checksums match, extract the ZIP
```

**[SCREENSHOT PLACEHOLDER: SourceForge download page for rEFInd]**

**[SCREENSHOT PLACEHOLDER: SHA-256 verification in PowerShell]**

### 5. Install rEFInd from Windows

**Steps:**

```
[ ] Open extracted refind-bin-0.14.0 folder
[ ] Locate refind-install.bat
[ ] Right-click → "Run as administrator"
[ ] Accept UAC prompt
[ ] rEFInd installs to EFI/Boot/bootx64.efi and registers in NVRAM
[ ] Reboot to BIOS (F2/Del at POST)
[ ] Verify "rEFInd" appears in boot options
```

**[SCREENSHOT PLACEHOLDER: refind-install.bat running with administrator privileges]**

**[SCREENSHOT PLACEHOLDER: BIOS boot menu showing rEFInd entry]**

**ESP layout after install:**

```
EFI/
├── refind/
│   ├── refind_x64.efi      # the boot manager binary
│   ├── refind.conf         # menu configuration
│   └── aipc/               # created later in step 9
│       ├── vmlinuz
│       └── initrd.img
└── Boot/
    └── bootx64.efi         # fallback copy some firmware boots instead
```

The menuentry appended to `refind.conf` (by `targets/windows/install-windows.ps1`, or by hand):

```
menuentry "AIPC Bazzite Installer (UNVERIFIED on Strix Halo)" {
    icon /EFI/refind/icons/os_linux.png
    loader /EFI/refind/aipc/vmlinuz
    initrd /EFI/refind/aipc/initrd.img
    options "root=live:LABEL=AIPC_LIVE rd.live.image quiet"
}
```

**Q1 Fallback: If rEFInd does NOT register in NVRAM**

Some Strix Halo firmware implementations may not persist rEFInd's boot entry. If rEFInd is missing from the boot menu:

```
[ ] Boot back to Windows
[ ] Open PowerShell as administrator
[ ] Run: bcdedit /create /d "rEFInd" /application bootsector
[ ] Note the returned {GUID}
[ ] Run: bcdedit /set {GUID} device partition=E:
[ ] Run: bcdedit /set {GUID} path \EFI\refind\refind_x64.efi
[ ] Run: bcdedit /displayorder {GUID} /addlast
[ ] Reboot and verify rEFInd appears in boot menu
```

**[SCREENSHOT PLACEHOLDER: bcdedit commands in PowerShell]**

---

## Disk Partitioning

### 6. Shrink Windows C: Drive

**Steps:**

```
[ ] Open Disk Management (diskmgmt.msc)
[ ] Right-click C: → "Shrink Volume"
[ ] Enter shrink size: 153600 MB (150 GB)
[ ] Click "Shrink" → wait for completion
[ ] Verify 150 GB "Unallocated" appears after C:
```

**[SCREENSHOT PLACEHOLDER: Disk Management shrink dialog with 150 GB entered]**

**[SCREENSHOT PLACEHOLDER: Disk Management showing 150 GB Unallocated]**

**BitLocker check:** If BitLocker is still on, the shrink option may be disabled or reduced. Return to §9.1 pre-flight and disable BitLocker.

### 7. Create 30 GB exFAT Install Partition

**Steps:**

```
[ ] Open Command Prompt as administrator
[ ] Run diskpart:
    diskpart
[ ] List disks:
    list disk
[ ] Select the NVMe (usually Disk 0):
    select disk 0
[ ] List partitions:
    list partition
[ ] Create a 30 GB primary partition in unallocated space:
    create partition primary size=30720
[ ] Select the new partition:
    select partition 3 (or the number shown)
[ ] Format as exFAT (NOT FAT32 — squashfs payload can exceed 4 GiB):
    format fs=exfat quick label="AIPC_LIVE"
[ ] Assign a drive letter (e.g., Z:):
    assign letter=Z
[ ] Exit diskpart:
    exit
```

**[SCREENSHOT PLACEHOLDER: diskpart commands creating 30 GB partition]**

**[SCREENSHOT PLACEHOLDER: Disk Management showing 30 GB exFAT partition]**

**Result:** 30 GB exFAT partition (Z:, label AIPC_LIVE) + 120 GB Unallocated remains.

> **⚠ Do NOT format or partition the remaining 120 GB from Windows.** It must stay
> unallocated — the bazzite installer claims it directly in step 11.

### 8. Download and Verify Bazzite-DX ISO

**Steps:**

```
[ ] Download vanilla bazzite-dx ISO:
    https://download.bazzite.gg/bazzite-stable-amd64.iso
[ ] Download the CHECKSUM file:
    https://download.bazzite.gg/bazzite-stable-amd64.iso-CHECKSUM
[ ] Verify SHA-256 in PowerShell:
    Get-FileHash bazzite-stable-amd64.iso -Algorithm SHA256
[ ] Compare the hash with the .CHECKSUM file
[ ] If checksums match, proceed
```

**[SCREENSHOT PLACEHOLDER: Get-FileHash verification in PowerShell]**

### 9. Extract ISO Contents to Install Partition

**Steps:**

```
[ ] Mount the Bazzite ISO in Windows (double-click the .iso file)
[ ] Note the mounted ISO drive letter (e.g., E:)
[ ] Open File Explorer
[ ] Copy the LiveOS folder from the ISO to Z:\ (Z:\LiveOS\)
[ ] Create folder Z:\EFI\refind\aipc\
[ ] Copy vmlinuz* from the ISO to Z:\EFI\refind\aipc\vmlinuz
[ ] Copy initrd* from the ISO to Z:\EFI\refind\aipc\initrd.img
[ ] Dismount the ISO
```

> **Why exFAT, not FAT32:** The LiveOS squashfs payload can exceed FAT32's 4 GiB
> single-file limit. Use exFAT for the AIPC_LIVE partition.

**[SCREENSHOT PLACEHOLDER: File Explorer showing extracted files on Z: drive]**

---

## Boot Flow

### 10. Reboot into rEFInd

**Steps:**

```
[ ] Reboot the machine
[ ] At POST, hit F11/F12 for boot menu (or wait for rEFInd auto-boot)
[ ] Select "rEFInd" from the boot menu
[ ] rEFInd menu appears with:
    - "bazzite-installer" (auto-detected from ISO on Z:)
    - "Windows Boot Manager"
[ ] Select "bazzite-installer"
[ ] Bazzite installer boots
```

**[SCREENSHOT PLACEHOLDER: rEFInd boot menu showing bazzite-installer]**

**[SCREENSHOT PLACEHOLDER: Bazzite installer boot screen]**

**Q2 Fallback: If rEFInd does NOT detect the ISO**

If rEFInd fails to chainload the ISO, use the Fedora Workstrap intermediate step:

```
[ ] Download Fedora Workstation Live ISO instead
[ ] Copy to Z: drive (same as step 9)
[ ] Boot Fedora Live via rEFInd
[ ] Install Fedora to the 120 GB unallocated space
[ ] After Fedora install, boot into Fedora
[ ] Run: curl -fsSL https://raw.githubusercontent.com/<user>/aipc_setup/main/tools/bootstrap.sh | bash
[ ] bootstrap.sh will bootc switch to bazzite-dx
```

This path is longer but more reliable if the bazzite installer's "install alongside" option is unavailable.

### 11. Run Bazzite Installer (from §9.4, with key difference)

**Steps:**

```
[ ] Select: "Install to free space" (NOT "Erase entire disk")
[ ] Target the 120 GB Unallocated region
[ ] Do NOT touch the Windows NTFS partition
[ ] Do NOT touch the 30 GB exFAT AIPC_LIVE install partition
[ ] Proceed with bazzite layout (BTRFS, /home and /var-home subvolumes)
[ ] Set hostname (e.g., `aipc-strix`), timezone, locale, username
[ ] Wait ~10 minutes
[ ] Reboot
```

**[SCREENSHOT PLACEHOLDER: Bazzite installer disk selection showing 120 GB unallocated]**

**⚠ CRITICAL:** Verify disk selection carefully. The bazzite installer defaults to "use entire disk" — you MUST select "install to free space" or manually partition to the 120 GB region.

### 12. Verify Dual-Boot Menu

**Steps:**

```
[ ] After reboot, rEFInd menu appears automatically
[ ] Verify entries:
    - "bazzite-dx" (new install)
    - "Windows Boot Manager" (pre-installed Windows)
[ ] Boot bazzite-dx first → verify desktop loads
[ ] Reboot, select "Windows Boot Manager" → verify Windows loads
[ ] Reboot, boot bazzite-dx again → continue to §9.5 Bootstrap
```

**[SCREENSHOT PLACEHOLDER: rEFInd menu showing both bazzite-dx and Windows Boot Manager]**

**Dual-boot soak period:** Both OSes remain bootable for 30 days. Do NOT wipe Windows yet.

---

## Post-Install Cleanup (30-Day Deferred)

### 13. Wait 30 Days and Verify

**Steps:**

```
[ ] Use bazzite-dx daily for 30 days
[ ] Run `aipc doctor` weekly — all checks must pass
[ ] Verify:
    - All Phase 0 hardware checks pass (rocm-smi, xdna-smi, etc.)
    - Voice assistant works end-to-end
    - No regressions in desktop stability
    - Network (Wi-Fi/Ethernet) reliable
[ ] At day 30, confirm you no longer need Windows rollback
```

**⚠ STOP:** If `aipc doctor` reports any errors, investigate before wiping Windows. The 30-day soak is your safety margin.

### 14. Wipe Windows (via future `aipc disk wipe-windows` CLI)

**Note:** This CLI does not exist yet. This spec defines its contract; implementation is a future OpenSpec change.

**Expected CLI behavior:**

```
[ ] Run: sudo aipc disk wipe-windows
[ ] CLI displays interactive confirmation:
    "This will REMOVE:
     - Windows NTFS partition (~100 GB)
     - 30 GB exFAT AIPC_LIVE install partition
     - Auto-extend BTRFS into freed space
     No rollback possible. Continue? (yes/no)"
[ ] Type: yes
[ ] CLI checks:
    - `aipc doctor` is green (all checks pass)
    - ≥30 days elapsed since install
[ ] If checks pass, CLI proceeds:
    - Removes Windows NTFS partition
    - Removes 30 GB exFAT AIPC_LIVE install partition
    - Extends BTRFS filesystem into freed space
    - Exits 0
[ ] Reboot → verify only bazzite-dx boots, rEFInd gone
```

**CLI contract (for future implementation):**

- **Interactive confirmation prompt** naming partitions to be wiped
- **Refuses to run** unless `aipc doctor` is green AND ≥30 days elapsed
- **Removes** Windows NTFS partition + 30 GB exFAT AIPC_LIVE install partition
- **Auto-extends** BTRFS filesystem into freed space
- **Exits non-zero** with single-line diagnosis on any failure
- **No force flag** — safety checks are mandatory

### 15. Manual Fallback (gparted + btrfs resize)

**If the CLI is not yet available and you want to wipe before it ships:**

**Steps:**

```
[ ] Install gparted (if not present):
    sudo rpm-ostree install gparted (reboot required)
[ ] Open gparted from application menu
[ ] Identify partitions:
    - /dev/nvme0n1p1: EFI System Partition (DO NOT TOUCH)
    - /dev/nvme0n1p2: Windows NTFS (DELETE)
    - /dev/nvme0n1p3: 30 GB exFAT AIPC_LIVE (DELETE)
    - /dev/nvme0n1p4: BTRFS (RESIZE)
[ ] Right-click Windows NTFS → "Delete"
[ ] Right-click 30 GB exFAT AIPC_LIVE → "Delete"
[ ] Right-click BTRFS → "Resize/Move"
[ ] Extend to maximum available size
[ ] Click "Apply All Operations"
[ ] Wait for resize to complete (may take 30+ minutes)
[ ] Reboot → verify BTRFS is full size
[ ] Remove rEFInd from EFI (optional cleanup):
    sudo rm -rf /boot/efi/EFI/refind
    sudo efibootmgr -b XXXX -B (where XXXX is rEFInd boot entry)
```

**[SCREENSHOT PLACEHOLDER: gparted showing partitions before deletion]**

**[SCREENSHOT PLACEHOLDER: gparted resize dialog extending BTRFS]**

**⚠ WARNING:** Manual partitioning is irreversible. Triple-check partition numbers before deleting.

---

## Recovery (If Bootloader Bricked)

### 16. Restore from WinRE Backup

**If neither bazzite-dx nor Windows boots:**

**Steps:**

```
[ ] Power on the machine
[ ] At POST, hold Shift and repeatedly press F8 (or force WinRE via 3 failed boot attempts)
[ ] Select "Advanced options" → "Troubleshoot" → "Advanced options" → "System Image Recovery"
[ ] Select the System Image Backup created in pre-flight (step 1)
[ ] Follow prompts to restore Windows
[ ] After restore, Windows boots, bazzite-dx partition remains untouched
[ ] Re-run this runbook from step 4 (EFI loader setup) or switch to USB path
```

**[SCREENSHOT PLACEHOLDER: WinRE Advanced Options menu]**

**[SCREENSHOT PLACEHOLDER: System Image Recovery selection dialog]**

**Note:** WinRE lives on a hidden partition on every Windows 11 install and does NOT require a USB stick. This is why the System Image Backup in pre-flight is mandatory.

---

## Summary

**What this path achieves:**
- Installs bazzite-dx without any USB stick
- Leaves Windows bootable for 30-day soak
- Recovers via WinRE + System Image Backup (no USB)
- Converges on same vanilla bazzite-dx state as USB path

**Trade-offs vs USB path:**
- Higher risk (bootloader corruption = harder recovery)
- More steps (EFI loader, partitioning, dual-boot)
- Requires 30-day dual-boot soak before Windows wipe
- No rollback to bazzite USB (you never had one)

**When to use this path:**
- ONLY if you cannot acquire a USB stick
- If a USB stick becomes available before starting, use USB path instead (§9.3–§9.4)

**Success criteria:**
- rEFInd menu shows both bazzite-dx and Windows Boot Manager
- `aipc doctor` passes all checks for 30 consecutive days
- After 30-day soak, Windows partition wiped and BTRFS extended

**Next steps after bazzite-dx boots:**
- Continue to §9.5 Bootstrap in architecture.md
- Then §9.6 First-boot wizard (`aipc init`)
- Then Phase 0 hardware verification

---

**Runbook version:** 2026-07-01 (install-windows-direct OpenSpec change)
**Hardware target:** AMD Ryzen AI MAX+ 395 (Strix Halo), 128 GB unified RAM, UEFI firmware
