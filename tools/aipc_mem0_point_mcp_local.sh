#!/bin/sh
# aipc_mem0_point_mcp_local.sh — re-point the mem0 Claude plugin's MCP from the
# Mem0 SaaS (https://mcp.mem0.ai/mcp/, MEM0_API_KEY, 1000/1000 usage quota) to
# the LOCAL aipc-mem0 server (aipc_mem0/mcp_server.py, offline, pgvector +
# LiteLLM gateway). Idempotent.
#
# Run after any mem0 plugin UPDATE — the plugin reinstall restores the SaaS
# .mcp.json and this script re-applies the local redirect. opencode
# (~/.config/opencode/config.json) and hermes (~/.hermes/config.yaml) are stable
# user configs set once; this script only touches the fragile Claude cache.
# See modules/memory-mem0/README.md "Pointing agents at local mem0".
set -eu

# Locate the deployed mem0 module + venv (live-hotfix /etc path first, then the
# baked-image /usr/lib path — see docs/live-hotfix-workflow.md).
if [ -d /etc/aipc/mem0/aipc_mem0 ] && [ -x /etc/aipc/mem0/venv/bin/python ]; then
  PYDIR=/etc/aipc/mem0
  VENV=/etc/aipc/mem0/venv/bin/python
elif [ -d /usr/lib/aipc-mem0/aipc_mem0 ] && [ -x /usr/lib/aipc-mem0/venv/bin/python ]; then
  PYDIR=/usr/lib/aipc-mem0
  VENV=/usr/lib/aipc-mem0/venv/bin/python
else
  echo "ERROR: aipc-mem0 module/venv not found under /etc/aipc/mem0 or /usr/lib/aipc-mem0" >&2
  exit 1
fi

count=0
for f in "$HOME"/.claude/plugins/cache/mem0-plugins/mem0/*/.mcp.json; do
  [ -f "$f" ] || continue
  tmp=$(mktemp)
  cat > "$tmp" <<EOF
{
  "mcpServers": {
    "mem0": {
      "_comment": "Redirected to LOCAL aipc-mem0 (offline; no SaaS quota). Re-apply with tools/aipc_mem0_point_mcp_local.sh after a plugin update.",
      "type": "stdio",
      "command": "$VENV",
      "args": ["-m", "aipc_mem0.mcp_server"],
      "env": {
        "PYTHONPATH": "$PYDIR",
        "MEM0_TELEMETRY": "False"
      }
    }
  }
}
EOF
  mv "$tmp" "$f"
  echo "rewrote $f -> local mem0 ($VENV)"
  count=$((count + 1))
done

if [ "$count" -eq 0 ]; then
  echo "No mem0 plugin .mcp.json found in ~/.claude/plugins/cache — is the mem0 plugin installed?" >&2
  exit 1
fi
echo "Done ($count file(s)). Restart Claude Code for the mem0 MCP to reconnect locally."
