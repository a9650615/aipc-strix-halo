# Design — windows-oneclick-installer

## Decisions

### D1 — Live payload partition is exFAT, not FAT32

The bazzite-dx squashfs/ISO payload exceeds FAT32's 4 GiB single-file
limit. The install-windows-direct runbook specified FAT32 (step 7), which
is a latent blocker — the payload would not fit.

**Chosen:** create the 30 GB live partition as **exFAT** (`-FileSystem
exFAT`), labelled `AIPC_LIVE`.

- Alternatives considered:
  - **FAT32** (runbook's original choice) — rejected, 4 GiB file ceiling.
  - **NTFS** — rEFInd has read support via a driver but reliability is
    weaker than exFAT; not worth the saved partition.

### D2 — Kernel + initrd on the FAT ESP; squashfs on the exFAT live partition

The ESP is FAT (small, firmware-readable). The full ISO/squashfs does not
fit there. Split the boot payload: `vmlinuz` + `initrd` live on the ESP
under `EFI/refind/aipc/`; the squashfs/ISO body lives on the exFAT
`AIPC_LIVE` partition. rEFInd boots the kernel with
`root=live:LABEL=AIPC_LIVE` (+ `rd.live.image`).

- Alternatives considered:
  - **Whole ISO on the ESP** — rejected, FAT32 4 GiB limit again.
  - **rEFInd ISO chainload** — kept as the Q1 fallback (see D6), not the
    primary path, because in-place kernel+initrd gives clearer cmdline
    control over the live source.

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
against the upstream checksum file (`refind-bin-0.14.0.zip.txt` and the
bazzite CHECKSUM) BEFORE `Expand-Archive` / copy / execute. Hard abort on
mismatch.

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
- **Risk: FAT32 4 GiB ceiling silently truncates the payload** →
  Mitigation: live partition is exFAT (D1); kernel+initrd split from
  squashfs (D2).

## Implementation notes

- New target dir `targets/windows/` (parallels `targets/bootc/`,
  `targets/ansible/`).
- `install-windows.ps1`: elevated entry. Phases: (1) preflight guard,
  (2) verified download + install rEFInd to ESP, (3) verified download of
  bazzite ISO, (4) confirmed shrink of C: to yield 150 GiB unallocated,
  (5) create 30 GiB exFAT partition labelled `AIPC_LIVE` + stage live
  payload, (6) extract `vmlinuz`+`initrd` to the ESP and write a rEFInd
  menuentry booting `root=live:LABEL=AIPC_LIVE`, (7) print next-steps
  (reboot → pick entry → installer "install to free space" not "use entire
  disk").
- `preflight-check.ps1`: read-only subset of phase 1; exit non-zero +
  one-line diagnosis on any failure (mirrors the module `verify.sh`
  contract).
- Boot mechanism note: kernel+initrd live on FAT ESP (small); squashfs
  lives on the exFAT partition; this sidesteps FAT32's 4 GiB limit. rEFInd
  NVRAM persistence + Strix firmware boot is UNVERIFIED — carries the
  §7.3 Q1/Q2 fallbacks as documented comments, not code.

## Cross-references

- `docs/install-windows-direct-runbook.md` — the 16-step manual runbook this
  automates (steps 4–10).
- `install-windows-direct` design.md D1–D7 (rEFInd, ISO chainload, 30 GB
  partition, dual-boot 30-day soak, WinRE recovery, Secure Boot off,
  opt-in).
- `CLAUDE.md` §5 (no secrets), §8 (terse; README carries the why).
