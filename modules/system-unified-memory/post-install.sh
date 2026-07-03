#!/bin/sh
# post-install.sh — system-unified-memory
# Build-time: enable the GPP0/GPP1 wake-source fix unit. NO systemctl --now
# (build has no running init) — the unit's [Install] WantedBy=default.target
# runs it at real boot, before the user has a chance to suspend.
set -eu

chmod 0755 /usr/lib/aipc/gpp-wake-fix
systemctl enable gpp-wake-fix.service
