#!/bin/bash
# Flatpak entry — GUI shell; official codexbar CLI is invoked via /app/bin/codexbar host shim.
set -eu
export PYTHONPATH="/app/lib/codexbar-gui${PYTHONPATH:+:${PYTHONPATH}}"
export PATH="/app/bin:${PATH}"
# Platform: prefer Wayland inside the sandbox (reliable). Xcb often fails with
# "could not connect to display" / missing xcb-cursor after relaunch.
if [ -z "${QT_QPA_PLATFORM:-}" ]; then
  if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    export QT_QPA_PLATFORM=wayland
  elif [ -n "${DISPLAY:-}" ]; then
    export QT_QPA_PLATFORM=xcb
  fi
fi
exec python3 -m codexbar_gui "$@"