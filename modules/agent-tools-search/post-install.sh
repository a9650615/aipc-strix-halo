#!/bin/sh
# post-install.sh — agent-tools-search
# BUILD-TIME ONLY.
set -eu

# Enable SearXNG quadlet (enable only, init not running during build)
if [ -f /etc/containers/systemd/aipc-searxng.container ] || \
   [ -f /usr/lib/containers/systemd/aipc-searxng.container ]; then
    systemctl enable aipc-searxng.service 2>/dev/null || true
fi
