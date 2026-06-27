# system-base

Base packages, locale (en_US.UTF-8 + zh_TW.UTF-8), timezone (Asia/Taipei),
and image branding for the aipc image.

## What it does

- Installs core CLI utilities and bootc/BTRFS tooling via `packages.txt`.
- Writes `/etc/locale.conf` (en_US.UTF-8 primary, zh_TW.UTF-8 supported).
- Symlinks `/etc/localtime` → `Asia/Taipei` via `post-install.sh`.
- Writes `/etc/aipc/branding.env` with `IMAGE_REF` and `BUILD_DATE` stamped at build time
  from `$AIPC_IMAGE_REF` and `$AIPC_BUILD_DATE` env vars injected by the renderer.

## Dependencies

None.

## Idempotency

`post-install.sh` uses `ln -sf` and conditional checks; safe to re-run.
