#!/bin/bash
# post-install.sh for system-hardware-power-guard
# Build-time only (CLAUDE.md §8): enable the unit (a symlink write, not a
# running process) and stage the state dir. NO systemctl --now — the build
# container has no running init and no live sysfs to read.
set -euo pipefail

# Enable at boot (does not start). The .disabled marker in this module
# (shipped separately) plus ConditionPathExists keeps it from auto-starting
# until a hardware-verified run flips it off — see CLAUDE.md §9.
systemctl enable power-guard.service 2>/dev/null || true

# Stage the writable state dir.
install -d -m 0755 /var/lib/aipc-power-guard

echo "power-guard: unit enabled (start via: systemctl start power-guard OR aipc power-guard enable)"
