#!/bin/bash
# Flatpak entry — GUI shell; official codexbar CLI is invoked via /app/bin/codexbar host shim.
set -eu
export PYTHONPATH="/app/lib/codexbar-gui${PYTHONPATH:+:${PYTHONPATH}}"
export PATH="/app/bin:${PATH}"

# Platform policy (multi-monitor HiDPI / Plasma):
# - Prefer native Wayland so cursor + QScreen layout match the panel (SNI).
# - XWayland (xcb) uses a different virtual desktop origin/scale than KWin
#   logical layout → popover lands on the wrong monitor.
# Force X11 only if explicitly requested: CODEXBAR_FORCE_XCB=1
# Force Wayland: CODEXBAR_NATIVE_WAYLAND=1 (default path when WAYLAND_DISPLAY set)
_force_xcb=0
case "${CODEXBAR_FORCE_XCB:-}" in
  1|true|TRUE|yes|YES|on|ON) _force_xcb=1 ;;
esac

if [ -z "${QT_QPA_PLATFORM:-}" ] || [ "${_force_xcb}" -eq 1 ]; then
  if [ "${_force_xcb}" -eq 1 ] && [ -n "${DISPLAY:-}" ]; then
    export QT_QPA_PLATFORM=xcb
    export GDK_BACKEND="${GDK_BACKEND:-x11}"
  elif [ -n "${WAYLAND_DISPLAY:-}" ]; then
    export QT_QPA_PLATFORM=wayland
  elif [ -n "${DISPLAY:-}" ]; then
    export QT_QPA_PLATFORM=xcb
    export GDK_BACKEND="${GDK_BACKEND:-x11}"
  fi
fi

exec python3 -m codexbar_gui "$@"
