## Why

The current install entrypoints are executable but not self-guiding: a user can clone the repo and still be unsure which step is safe, which prerequisites are missing, and which actions are destructive. The install path needs a keyboard-first guided flow that explains the next step and prevents obvious mistakes without becoming a large installer framework.

## What Changes

- Add a guided installer capability for root entrypoints on both Windows and Linux.
- Windows entrypoint gains a simple keyboard-operated menu/wizard for safe transfer: read-only checks, backup acknowledgement, destructive staging, basic settings reminders, and next-step instructions.
- Linux entrypoint gains a simple guided wrapper around `tools/bootstrap.sh` that confirms the user is on the installed vanilla bazzite-dx system before running bootstrap.
- The guided flow must keep current safety gates: no auto-reboot from Windows, no disk mutation without confirmation, no download use before checksum verification, and no claim that Strix Halo boot has been hardware-verified.
- No new cross-platform UI framework or heavy dependency; use native terminal capabilities first.

## Capabilities

### New Capabilities

- `guided-installer`: Keyboard-first guided install flow for repo-root Windows staging and Linux bootstrap entrypoints.

### Modified Capabilities

- None.

## Impact

- Affected files likely include `Install-AIPC-Windows.ps1`, `install-aipc-linux.sh`, `targets/windows/*.ps1`, `README.md`, and `targets/windows/README.md`.
- No module changes are expected.
- No new secrets, service startup, LiteLLM routing, bootc renderer, or Ansible renderer behavior is expected.
