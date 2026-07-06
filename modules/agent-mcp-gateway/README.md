# agent-mcp-gateway

Shared MCP registry contract (D9): the JSON schema for `/etc/aipc/mcp/servers.json`
and a fallback empty seed. Consumer modules (`dev-ai-mcp-dev-servers`,
`agent-browser`) register their MCP servers into this same file.

## Registry schema

`/etc/aipc/mcp/servers.json`:

```json
{
  "version": 1,
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home"],
      "transport": "stdio",
      "enabled": true,
      "consumers": ["dev-ai-mcp-dev-servers"]
    },
    {
      "name": "playwright",
      "command": "npx",
      "args": ["-y", "@playwright/mcp"],
      "transport": "stdio",
      "enabled": true,
      "consumers": ["agent-browser"],
      "profile_path": "/var/lib/aipc-agent/playwright-profile"
    },
    {
      "name": "github",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "transport": "stdio",
      "enabled": true,
      "consumers": ["dev-ai-mcp-dev-servers"],
      "env": {"GITHUB_TOKEN": "${SOPS_DECRYPTED:github_token}"}
    }
  ]
}
```

Fields per entry:

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Unique server id |
| `command` | yes | Executable to launch the server |
| `args` | yes | Argument list (array of strings) |
| `transport` | yes | `stdio` (only transport in use as of phase-4-agent) |
| `enabled` | yes | Whether the gateway should register it |
| `consumers` | yes | Module name(s) that registered this entry, for traceability |
| `profile_path` | no | Playwright-style entries needing a persistent browser profile dir |
| `env` | no | Map of env vars to set, values may reference `${SOPS_DECRYPTED:...}` (CLAUDE.md §5) |

## Seed

This module ships an empty `{"version": 1, "servers": []}` document at
`files/etc/aipc/mcp/servers.json` (task 6.2) so the file exists even before
any consumer module registers anything. Consumer modules that ship their
own `files/etc/aipc/mcp/servers.json` (e.g. `dev-ai-mcp-dev-servers`)
render their `COPY` after this module's (alphabetical module order, see
`tools/aipc_lib/modules.py::discover`) and so overwrite this empty seed
with their real entries — that's expected, not a conflict, as long as only
one consumer module ships the file at a time.

**Known gap (phase-4-agent#6.4):** `modules/dev-ai-mcp-dev-servers/files/etc/aipc/mcp/servers.json`
does not conform to the schema above yet — it's a flat `{name: {command,
args, env}}` object with no `version`/`servers` wrapper and no
`transport`/`enabled`/`consumers` fields per entry, and its
`post-install.sh` doesn't write/merge anything (the file is a static
`files/` copy, not generated at build time). `verify.sh` treats a
version-less file as legacy and only checks it's valid JSON; it does not
yet enforce the new schema against it. Fixing `dev-ai-mcp-dev-servers` to
emit the documented shape is Phase 6 work, out of scope here.

## Dependencies
- dev-ai-mcp-dev-servers (registers filesystem/github entries)
- agent-browser (registers the playwright entry, task 6.3)

## Spec
openspec/changes/phase-4-agent — tasks 1.8, 6.1, 6.2, 6.4
