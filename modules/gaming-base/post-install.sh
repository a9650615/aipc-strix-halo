#!/bin/sh
# post-install.sh — gaming-base
# Build-time only: copy desktop entry. No systemctl --now.
set -eu

install -Dm0644 \
    "${AIPC_MODULE_SRC}/files/usr/share/wayland-sessions/gamescope.desktop" \
    /usr/share/wayland-sessions/gamescope.desktop
