# agent-mcp-gateway

Shared MCP registry contract (D9).

The registry file lives at `modules/dev-ai-mcp-dev-servers/files/etc/aipc/mcp/servers.json`.
This module does NOT duplicate it — it provides:
- verify.sh that validates the JSON shape of servers.json
- Cross-reference documentation

## Dependencies
- dev-ai-mcp-dev-servers (owns servers.json)

## Spec
openspec/changes/phase-4-agent — task 1.8
