# ops-backup

Snapper-based BTRFS snapshot management with timeline retention policy.

## What it does

- Installs snapper via `packages.txt`.
- Ships a snapper timeline config at `/etc/snapper/configs/aipc-root` with retention: 7 daily / 4 weekly / 3 monthly.
- Declares managed subvolumes in `/etc/aipc/backup/subvols`: `/`, `/var`, `/home`.
- Pre-update snapshots are taken automatically when rpm-ostree updates run.

## Design decisions

- **D1**: Snapper timeline with 7d/4w/3m retention + pre-update hook. Balances recovery granularity against disk usage.
- **D7**: The `aipc restore` CLI is in ops-doctor scope — this module provides the snapshot infrastructure, ops-doctor provides the user-facing restore command.

## Notes

- BTRFS subvolume layout must be validated on target hardware before enabling.
- Snapper timeline runs via systemd timer; no `systemctl --now` at build time.

## Dependencies

- `system-base` (BTRFS filesystem assumed)

## Spec cross-ref

- `openspec/changes/phase-7-ops/design.md` §D1, §D7
