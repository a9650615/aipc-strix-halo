#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

registry=/etc/aipc/mcp/servers.json
if [ -f "$registry" ]; then
    jq -e '.servers[] | select(.name=="playwright-agent")' "$registry" >/dev/null 2>&1 || {
        echo "agent-browser: no playwright-agent entry in $registry" >&2
        exit 1
    }
fi

install_hint="run: distrobox enter node -- npm install -g @playwright/mcp"
if command -v distrobox >/dev/null 2>&1 && distrobox list 2>/dev/null | grep -qw node; then
    distrobox enter node -- sh -c 'command -v playwright-mcp' >/dev/null 2>&1 || {
        echo "agent-browser: playwright-mcp binary not found inside the node distrobox — $install_hint" >&2
        exit 1
    }
elif command -v playwright-mcp >/dev/null 2>&1; then
    :
else
    echo "agent-browser: playwright-mcp binary not found on host or in node distrobox — $install_hint" >&2
    exit 1
fi

exit 0
