#!/bin/sh
# post-install.sh — agent-orchestrator
# BUILD-TIME ONLY. No running services during image build.
set -eu

python3 -m venv /usr/lib/aipc-agent/venv
/usr/lib/aipc-agent/venv/bin/pip install --no-cache-dir -r /usr/lib/aipc-agent/requirements.txt

systemctl enable aipc-agent-orchestrator.service

# Enable quadlet units if present (enable only, init not running during build)
for unit in /etc/containers/systemd/aipc-agent-*.container; do
    [ -f "$unit" ] && systemctl enable "$(basename "$unit" .container).service" 2>/dev/null || true
done
