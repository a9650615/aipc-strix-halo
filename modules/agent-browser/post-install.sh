#!/bin/sh
# post-install.sh — agent-browser
# BUILD-TIME ONLY.
set -eu

# Persistent browser profile for the agent consumer (task 4.9) — distinct
# from dev-ai-mcp-dev-servers' own "playwright" entry (npx ephemeral
# default profile), so agent and dev browser sessions never share
# cookies/storage state.
install -d -m 0700 /var/lib/aipc-agent/browser-profile

# @playwright/mcp itself is NOT installed here: Node/npm only exist inside
# the `node` distrobox (dev-distrobox-templates), which is assembled by the
# user at first run, not at image-build time (no distrobox exists yet
# inside this build container) — same reason dev-ai-claude-code/dev-ai-
# opencode document their npm installs as a runtime command instead of
# running them from post-install.sh. See README for the exact command.

# Idempotent replace-if-exists merge of this module's registry entry into
# the shared /etc/aipc/mcp/servers.json (task 6.3). Seeds the file if
# agent-mcp-gateway's task 6.2 seed hasn't landed yet. Pure JSON edit, no
# network/service needed, so this is safe at build time.
registry=/etc/aipc/mcp/servers.json
entry=/etc/aipc/mcp/playwright.json
mkdir -p "$(dirname "$registry")"
[ -f "$registry" ] || printf '{"version":1,"servers":[]}' > "$registry"
tmp="$(mktemp)"
jq --slurpfile new "$entry" \
   '.servers |= (map(select(.name != $new[0].name)) + $new)' \
   "$registry" > "$tmp"
mv "$tmp" "$registry"
