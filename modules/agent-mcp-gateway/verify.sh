#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

# Validate servers.json from dev-ai-mcp-dev-servers
servers_json="/etc/aipc/mcp/servers.json"
if [ -f "$servers_json" ]; then
    jq empty "$servers_json" 2>/dev/null || {
        echo "agent-mcp-gateway: $servers_json is not valid JSON" >&2
        exit 1
    }
fi
exit 0
