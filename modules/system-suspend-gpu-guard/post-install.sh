#!/bin/bash
# post-install.sh for system-suspend-gpu-guard
# Build-time only (CLAUDE.md §8): enable the unit (a symlink write, not a
# running process). NO systemctl --now — the build container has no running
# init and no live sysfs/GPU to read.
set -euo pipefail

systemctl enable suspend-gpu-guard.service 2>/dev/null || true

echo "suspend-gpu-guard: unit enabled (kill switch: touch /etc/aipc/suspend-gpu-guard.disabled)"
