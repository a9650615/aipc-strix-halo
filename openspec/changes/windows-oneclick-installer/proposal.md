# windows-oneclick-installer

`install-windows-direct` shipped a 16-step manual runbook only. The user
needs a one-click launcher: run one elevated PowerShell script in Windows,
it performs the deterministic, error-prone steps (verified downloads,
rEFInd install, disk partitioning, live-payload staging, boot-entry
generation) automatically, leaving only the physical steps (BIOS, one boot
test, picking the installer disk) to the user. Manual SHA-typing and
`diskpart` are the two highest-risk failure points; automation with hard
guards removes them.

This change adds no new module and modifies no existing one. It adds a new
render-adjacent target dir `targets/windows/` (paralleling `targets/bootc/`
and `targets/ansible/`) holding the launcher scripts.

## Capabilities

- `windows-oneclick-installer` — added. Spec delta in
  `specs/windows-oneclick-installer/spec.md`. No existing capability is
  modified.
