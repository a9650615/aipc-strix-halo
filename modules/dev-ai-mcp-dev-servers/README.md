# dev-ai-mcp-dev-servers

Development MCP servers — Filesystem, GitHub, and Playwright — registered
with the Phase 4 agent-mcp-gateway (when available).

## What it does

- Installs three MCP server npm packages globally:
  `@anthropic-ai/mcp-filesystem`, `@anthropic-ai/mcp-github`,
  `@anthropic-ai/mcp-playwright`.
- Writes a registration manifest at `/etc/aipc/mcp-servers.d/dev-servers.yaml`.

## Status

**Disabled** — blocked on `phase-4-agent` (agent-mcp-gateway not yet specced).
The `.disabled` marker is removed once the gateway module lands.

## Dependencies

- `llm-litellm` (gateway for any model calls from MCP tools).
- `dev-distrobox-templates` (Node template for npm packages).

## Consumers

Phase 4 agent-mcp-gateway reads the manifest to register these servers.
