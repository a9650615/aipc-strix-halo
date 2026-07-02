# Design — windows-oneclick-installer

## Decisions

### D1 — Live payload partition is FAT32, not exFAT

Bazzite ships an **Anaconda installer ISO** (`images/install.img`), not a
dracut live ISO (`LiveOS/squashfs.img`). The largest file in the whole
installer tree is `images/install.img` at ~2.8 GiB — under FAT32's 4 GiB
per-file limit. The installer initrd mounts the payload partition via
`inst.stage2=hd:LABEL=…` and reliably reads **vfat**; exFAT support in that
initrd is not guaranteed, so exFAT risks the installer never finding stage2.

**Chosen:** create the 30 GB live partition as **FAT32** (`-FileSystem
FAT32`), labelled `AIPC_LIVE` (≤ 11 chars, satisfies FAT32's label limit).

- Alternatives considered:
  - **exFAT** (the original choice, on the mistaken premise of a > 4 GiB
    squashfs) — rejected; no file exceeds 4 GiB, and the installer initrd
    may not mount exFAT.
  - **NTFS** — the installer initrd does not mount NTFS read-write for
    stage2; rejected.

### D2 — Kernel + initrd load from the AIPC_LIVE volume, not the ESP

A default Windows ESP is often only ~256 MiB with a large chunk already
consumed by `Microsoft\Boot\`; Bazzite's `initrd.img` alone is ~242 MiB,
so copying it onto the ESP alongside rEFInd routinely fails with "not
enough disk space." rEFInd reads FAT natively (no driver needed), so
instead the **entire ISO tree** (`images/install.img`, `images/pxeboot/
{vmlinuz,initrd.img}`, the `bazzite-stable/` OCI repo, `.treeinfo`, …) is
mirrored onto the FAT32 `AIPC_LIVE` partition — exactly what a
`dd`-written USB would contain — and the rEFInd menuentry points at it
with a `volume "AIPC_LIVE"` directive rather than staging a copy on the
ESP. rEFInd boots the kernel with `inst.stage2=hd:LABEL=AIPC_LIVE`,
matching the ISO's own grub.cfg (`inst.stage2=hd:LABEL=bazzite-x86_64-stable`)
with our partition label.

- Alternatives considered:
  - **Copy vmlinuz+initrd to the ESP** (original design) — rejected;
    measured ESP free space (168 MiB) is smaller than initrd.img (242 MiB)
    on real hardware.

- Alternatives considered:
  - **Copy only `LiveOS/` + kernel** (original design) — rejected; this is
    an Anaconda ISO with no `LiveOS/`, and Anaconda needs the full tree.
  - **rEFInd ISO chainload** — kept as the Q1 fallback (see D6), not the
    primary path, because in-place kernel+initrd gives clearer cmdline
    control over the install source.

### D3 — Every destructive disk operation is confirmation-gated

This repartitions the user's ONLY machine. A wrong `Resize-Partition` /
`Format-Volume` / `Remove-Partition` destroys Windows and their data.

**Chosen:** the entry script uses `[CmdletBinding(SupportsShouldProcess)]`
so `-WhatIf` dry-runs every destructive step, AND each destructive phase
prints its exact plan (drive, sizes) and requires an interactive
`Read-Host` "yes" before executing.

- Alternatives considered:
  - **`-Force` / no prompt** — rejected; this is the only machine, no
    rollback if the wrong disk/size is chosen.

### D4 — Downloads are SHA-256-verified against upstream checksums before use

Supply-chain risk: a tampered rEFInd zip or bazzite ISO executed/copied
verbatim.

**Chosen:** `Get-FileHash -Algorithm SHA256` is computed and compared
BEFORE `Expand-Archive` / copy / execute. rEFInd publishes no per-file
checksum, so its zip hash is **pinned to the release** in the script; the
bazzite ISO is verified against its upstream `-CHECKSUM` file. Hard abort on
mismatch. (rEFInd is also fetched from a `*.dl.sourceforge.net` mirror —
the `/files/.../download` URLs serve an HTML interstitial, not the binary.)

- Alternatives considered:
  - **Trust the HTTPS download** — rejected; HTTPS is not an integrity
    guarantee against a compromised mirror/CDN.

### D5 — The launcher is idempotent and re-runnable

Image rebuilds and recovery re-runs must not redo or double-apply steps.

**Chosen:** each phase skips if its output already exists and is verified
(rEFInd already registered, ≥150 GiB unallocated already present, a verified
ISO already staged, the `AIPC_LIVE` partition already formatted). Matches
the `tools/bootstrap.sh` idempotency pattern.

- Alternatives considered:
  - **Non-idempotent, re-partition every run** — rejected; destructive and
    wipes the staged payload on recovery.

### D6 — The boot mechanism is UNVERIFIED on Strix Halo; fallbacks are comments, not code

rEFInd persisting in NVRAM and booting the live kernel on this specific
AMI Aptio firmware is unverified (install-windows-direct §7.3 Q1/Q2).

**Chosen:** the script generates the primary rEFInd menuentry and prints a
clear "THIS BOOT PATH IS UNVERIFIED ON STRIX HALO — test once before
trusting it." The Q1 (`bcdedit /create` chainload) and Q2 (Fedora
Workstation Live + `bootc switch`) fallbacks ship as commented blocks, not
active code.

- Alternatives considered:
  - **Assert the boot works** — rejected; contradicts §7.3. Hardware boot
    test is the user's gate.

## Risks

- **Risk: wrong destructive disk op destroys Windows + user data** →
  Mitigation: every destructive op prints its plan and requires
  interactive `Read-Host` confirm; `SupportsShouldProcess` enables `-WhatIf`
  dry-run; preflight refuses if BitLocker is on, C: cannot shrink by 150 GiB,
  firmware is not UEFI, or Secure Boot is enabled; mutation also requires the
  user to acknowledge a completed non-USB System Image Backup for WinRE recovery.
- **Risk: tampered download executed/copied** → Mitigation: SHA-256 verify
  each download against its upstream checksum before any use; hard abort on
  mismatch.
- **Risk: rEFInd does not persist/boot on Strix Halo firmware** →
  Mitigation: boot path documented as UNVERIFIED; Q1 (bcdedit chainload) +
  Q2 (Fedora Live + bootc switch) fallbacks included as comments; script
  prints a "test once" warning and never asserts boot success.
- **Risk: installer initrd cannot mount the payload partition** →
  Mitigation: live partition is FAT32, which the Anaconda initrd reliably
  mounts (D1); no installer file exceeds FAT32's 4 GiB per-file limit; the
  full tree is mirrored so `inst.stage2=hd:LABEL=AIPC_LIVE` resolves (D2).

## Implementation notes

- New target dir `targets/windows/` (parallels `targets/bootc/`,
  `targets/ansible/`).
- `install-windows.ps1`: elevated entry. Phases: (1) preflight guard,
  (2) verified download + install rEFInd to ESP, (3) verified download of
  bazzite ISO, (4) confirmed shrink of C: to yield 150 GiB unallocated,
  (5) create 30 GiB FAT32 partition labelled `AIPC_LIVE` + mirror the full
  installer tree (including `vmlinuz`+`initrd`), (6) write a rEFInd
  menuentry with `volume "AIPC_LIVE"` booting `inst.stage2=hd:LABEL=AIPC_LIVE`,
  (7) print next-steps
  (reboot → pick entry → installer "install to free space" not "use entire
  disk").
- `preflight-check.ps1`: read-only subset of phase 1; exit non-zero +
  one-line diagnosis on any failure (mirrors the module `verify.sh`
  contract).
- Boot mechanism note: the ESP holds only rEFInd itself (too small for a
  ~242 MiB initrd); the full Anaconda installer tree, including
  `vmlinuz`/`initrd`, lives on the FAT32 `AIPC_LIVE` partition and rEFInd
  loads it via a `volume "AIPC_LIVE"` directive, booting
  `inst.stage2=hd:LABEL=AIPC_LIVE`. rEFInd NVRAM persistence + Strix
  firmware boot is UNVERIFIED — carries the §7.3 Q1/Q2 fallbacks as
  documented comments, not code.

## Cross-references

- `docs/install-windows-direct-runbook.md` — the 16-step manual runbook this
  automates (steps 4–10).
- `install-windows-direct` design.md D1–D7 (rEFInd, ISO chainload, 30 GB
  partition, dual-boot 30-day soak, WinRE recovery, Secure Boot off,
  opt-in).
- `CLAUDE.md` §5 (no secrets), §8 (terse; README carries the why).
