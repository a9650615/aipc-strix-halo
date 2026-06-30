# ops-firstboot

First-boot wizard: 3-screen TUI for persona setup, editor confirmation,
and cloud key SOPS encryption. Runs once via systemd ConditionPathExists.

## What it does

- Ships a wizard schema stub at `/etc/aipc/firstboot/wizard.yaml` defining
  the 3-step flow: persona record → editor confirm → cloud key SOPS-encrypt.
- Installs `aipc-firstboot.service` (systemd unit with `ConditionPathExists=!/var/lib/aipc/firstboot-done`).
- Installs `aipc-init` shim to `/usr/lib/aipc/aipc-init`.
- The TUI implementation itself is future work; this module declares the contract.

## Design decisions

- **D3**: 3-screen wizard (persona / editor / cloud-keys). Runs once on first
  boot, creates `/var/lib/aipc/firstboot-done` sentinel to prevent re-runs.

## Notes

- `aipc-firstboot.service` is enabled (not started) at build time — no `--now`.
- The TUI wizard is not yet implemented; enabling this module requires the
  `aipc-init` Python TUI to exist.

## Dependencies

- `secrets-sops` (cloud key SOPS encryption)
- `system-base` (base system)

## Spec cross-ref

- `openspec/changes/phase-7-ops/design.md` §D3
