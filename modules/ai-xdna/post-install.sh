#!/bin/sh
# post-install.sh — ai-xdna
# Idempotent: safe to re-run on image rebuilds.
set -eu

# Load driver now and on every boot
modprobe amd_xdna 2>/dev/null || true
install -D -m 0644 "$(dirname "$0")/modprobe.d/amd-xdna.conf" \
    /etc/modprobe.d/amd-xdna.conf 2>/dev/null || \
    printf 'amd_xdna\n' > /etc/modules-load.d/amd-xdna.conf

# udev rule: /dev/accel/accel0 accessible to render group
rule=/etc/udev/rules.d/70-amd-xdna.rules
if [ ! -f "${rule}" ]; then
  printf 'KERNEL=="accel*", SUBSYSTEM=="accel", GROUP="render", MODE="0660"\n' > "${rule}"
  udevadm control --reload-rules 2>/dev/null || true
  udevadm trigger --subsystem-match=accel 2>/dev/null || true
fi
