# gaming-ai-overlay

Voice-driven AI overlay for gaming, running inside a Python distrobox.

## What it does

- Ships a configuration stub at `/etc/aipc/gaming/overlay.yaml` with default hotkey bindings.
- The actual overlay runs in a Python distrobox (not host-installed) — no host packages needed.
- Integrates with the Pipecat voice pipeline for in-game voice AI interaction.

## Design decisions

- **D3**: Voice + overlay both shipped as a single user experience. The overlay is the unified surface for voice commands during gameplay.
- **D6**: Uses the gamescope-overlay protocol for screen capture and input injection. The overlay communicates with gamescope via its input API.

## Notes

- No host packages — everything runs distrobox-side to avoid polluting the bootc image.
- Hotkey `Super+G` toggles the overlay on/off by default.
- No `post-install.sh`: `files/` is COPYed straight to its final path by the
  renderer, so a build-time re-install from `${AIPC_MODULE_SRC}` (never set
  anywhere) was redundant and broken. Removed 2026-07-06.

## Dependencies

- `gaming-base` (gamescope session)
- `voice-pipecat` (voice pipeline)

## Spec cross-ref

- `openspec/changes/phase-5-gaming/design.md` §D3, §D6
