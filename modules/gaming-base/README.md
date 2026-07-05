# gaming-base

Gamescope session and Steam runtime base for the aipc gaming experience.

## What it does

- Installs gamescope and steam via `packages.txt`.
- Registers a gamescope wayland-session desktop entry so users can select it at login.
- Gamescope is installed but **not** the default session — users opt in via the login manager.

## Design decisions

- **D1**: gamescope installed, not default-entered. Users choose gamescope from the session picker.
- **D2**: Steam is the primary game library. Heroic Games Launcher is opt-in (not installed by this module).

## Notes

- On bazzite-dx, gamescope and steam may already be preinstalled. If `packages.txt` entries are no-ops, that is expected.
- No host pip/npm installs. All AI overlay work lives in `gaming-ai-overlay` (distrobox-side).
- No `post-install.sh`: `files/` is COPYed straight to its final path by the
  renderer, so a build-time re-install from `${AIPC_MODULE_SRC}` (never set
  anywhere) was redundant and broken. Removed 2026-07-06.

## Dependencies

- `system-base` (base packages, locale)

## Spec cross-ref

- `openspec/changes/phase-5-gaming/design.md` §D1, §D2
