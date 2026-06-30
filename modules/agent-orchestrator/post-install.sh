#!/bin/sh
# post-install.sh — agent-orchestrator
# BUILD-TIME ONLY. No running services during image build.
set -eu

# Enable quadlet units if present (enable only, init not running during build)
for unit in /etc/containers/systemd/aipc-agent-*.container; do
    [ -f "$unit" ] && systemctl enable "$(basename "$unit" .container).service" 2>/dev/null || true
done
