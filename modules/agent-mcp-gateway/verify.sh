#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

servers_json="/etc/aipc/mcp/servers.json"
if [ ! -f "$servers_json" ]; then
    exit 0
fi

jq empty "$servers_json" 2>/dev/null || {
    echo "agent-mcp-gateway: $servers_json is not valid JSON" >&2
    exit 1
}

# Schema (README.md): {"version": 1, "servers": [{name, command, args,
# transport, enabled, consumers, ...}]}. A file with no top-level
# "version" key predates the schema (legacy dev-ai-mcp-dev-servers shape,
# phase-4-agent#6.4) -- valid-JSON above is all it gets until migrated.
if ! jq -e 'has("version")' "$servers_json" >/dev/null 2>&1; then
    exit 0
fi

jq -e '.servers | type == "array"' "$servers_json" >/dev/null 2>&1 || {
    echo "agent-mcp-gateway: $servers_json .servers must be an array" >&2
    exit 1
}

malformed=$(jq -r '
  [.servers[] | select(
    (has("name") and (.name | type == "string")) and
    (has("command") and (.command | type == "string")) and
    (has("args") and (.args | type == "array")) and
    (has("transport") and (.transport | type == "string")) and
    (has("enabled") and (.enabled | type == "boolean")) and
    (has("consumers") and (.consumers | type == "array"))
    | not
  )] | length' "$servers_json")

if [ "$malformed" -gt 0 ]; then
    echo "agent-mcp-gateway: $servers_json has $malformed malformed entr(y/ies) (need name/command/args/transport/enabled/consumers)" >&2
    exit 1
fi

exit 0
