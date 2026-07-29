#!/bin/bash
# post-install.sh for system-hardware-power-guard
# Build-time only (CLAUDE.md §8): enable the unit (symlink write, not a
# running process) and stage state dirs. NO systemctl --now.
set -euo pipefail

install -d -m 0755 /var/lib/aipc-power-agent
install -d -m 0755 /var/lib/aipc-power-guard
install -d -m 0755 /etc/aipc/power-agent

# Prefer the unified agent; drop legacy unit enablement if present on the image.
systemctl disable power-guard.service 2>/dev/null || true
systemctl disable aipc-usbc-core-policy.service 2>/dev/null || true
systemctl enable aipc-power-agent.service 2>/dev/null || true

echo "aipc-power-agent: unit enabled (start via: systemctl start aipc-power-agent OR aipc power-agent enable)"
echo "aipc-power-agent: legacy power-guard / aipc-usbc-core-policy should be disabled; agent owns both policies"
