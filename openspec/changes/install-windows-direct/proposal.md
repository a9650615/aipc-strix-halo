## Why

The default install path (`docs/architecture.md` §9) requires a USB stick for the bazzite-dx live installer. Users who cannot acquire a USB stick — but who have a working Windows 11 install, a UEFI machine, and ≥150 GB of unallocated NVMe space — are blocked. The Mac in the existing flow is only used to write the USB; it does not help if no USB is available at either end.

This change adds an **alternative** install path that boots the bazzite-dx installer directly from the machine's own NVMe via an EFI boot manager dropped into the ESP from Windows. The USB path remains the primary recommendation; this is the no-USB fallback.

## What Changes

- `system-foundation` capability gains a second bootstrap path (R6b: Windows-direct) alongside the existing one (R6a: USB Live). R6 itself is rewritten to permit either path.
- A new `system-foundation` requirement R8 (Windows Recovery Path) makes the on-disk WinRE the documented recovery mechanism when no USB stick exists.
- New section in `docs/architecture.md`: §9 Alt covering the Windows-direct flow end to end.
- New runbook: `docs/install-windows-direct-runbook.md` with ~30 numbered steps.
- **User-visible defaults: BIOS Secure Boot remains Disabled** (no change from §9.2); the new path also dual-boots Windows + bazzite-dx for a 30-day soak before Windows wipe (new, but opt-in — only applies to users who take this path).
- No `modules/` changes. No new dependency on the image side.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `system-foundation`: R6 "Bootstrap From Vanilla bazzite-dx" is generalised to permit either USB-live boot (R6a, unchanged behaviour) or Windows-direct boot (R6b, new). One new requirement (R8 Windows Recovery Path) is added for users on the R6b path who have no USB recovery option.

## Impact

- `docs/architecture.md`: new §9 Alt section. §9.1, §9.2, §9.5, §9.6, §9.7, §9.8 remain unchanged.
- `docs/install-windows-direct-runbook.md`: new file.
- `tools/`: no changes in this change. A future change defines and ships an `aipc disk wipe-windows` CLI used at day 30; this proposal specifies its contract only.
- No new external dependency on the image. rEFInd is installed from the user's Windows side and lives only in the ESP; it is not part of the aipc bootc image.
- No security loosening beyond what §9.2 already calls (Secure Boot off).
