#!/bin/bash
# Run host official `codexbar` CLI (data plane) from inside the Flatpak sandbox.
set -eu
if command -v flatpak-spawn >/dev/null 2>&1; then
  exec flatpak-spawn --host codexbar "$@"
fi
# Fallback if host binary is visible via filesystem
if [ -x "${HOME}/.local/bin/codexbar" ]; then
  exec "${HOME}/.local/bin/codexbar" "$@"
fi
if [ -x /var/home/"${USER}"/.local/bin/codexbar ]; then
  exec /var/home/"${USER}"/.local/bin/codexbar "$@"
fi
echo "codexbar host CLI not found (install official CodexBar CLI)" >&2
exit 127
