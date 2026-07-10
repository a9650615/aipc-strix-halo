#!/bin/bash
# Flatpak entry — GUI shell; official codexbar CLI is invoked via /app/bin/codexbar host shim.
set -eu
export PYTHONPATH="/app/lib/codexbar-gui${PYTHONPATH:+:${PYTHONPATH}}"
export PATH="/app/bin:${PATH}"
# Prefer XWayland for tray popover positioning (same as host launcher)
if [ -n "${WAYLAND_DISPLAY:-}" ] && [ -n "${DISPLAY:-}" ] \
  && [ -z "${CODEXBAR_NATIVE_WAYLAND:-}" ] && [ -z "${QT_QPA_PLATFORM:-}" ]; then
  export QT_QPA_PLATFORM=xcb
fi
exec python3 -m codexbar_gui "$@"
