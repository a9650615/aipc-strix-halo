# agent-browser

Playwright MCP browser integration (D6).

Playwright MCP (`@playwright/mcp`) provides browser automation for the
agent framework. Node/npm only exist inside the `node` distrobox
(`dev-distrobox-templates`) — there is no Node on the bootc host image
itself — so Playwright MCP is installed and run there, same as
`dev-ai-claude-code`/`dev-ai-opencode`.

## Install

No build-time install step: the `node` distrobox is assembled by the user
at first run (`distrobox assemble create --file /etc/aipc/distrobox/node.ini`),
not at image-build time, so there's nothing to `npm install` into yet.
One-time step after that:

```
distrobox enter node -- npm install -g @playwright/mcp
```

Verified 2026-07-06 (in a Node/npm dev sandbox, not this repo's actual
distrobox): `npm install -g @playwright/mcp` (published version 0.0.77)
puts a `playwright-mcp` binary on `$PATH`; `playwright-mcp --version`
prints `Version 0.0.77` and `playwright-mcp --help` confirms a
`--user-data-dir <path>` flag for a persistent browser profile.

## Registry entry (task 6.3)

`files/etc/aipc/mcp/playwright.json` ships one entry (name
`playwright-agent`), merged idempotently into the shared
`/etc/aipc/mcp/servers.json` by `post-install.sh` — replace-if-exists on
`name`, safe to re-run on every image rebuild. Seeds the registry file
with `{"version":1,"servers":[]}` first if it doesn't exist yet (task 6.2
hasn't landed in `agent-mcp-gateway`). Fields match the schema in
`openspec/changes/phase-4-agent/specs/agent-runtime/spec.md` ("Shared MCP
Registry At /etc/aipc/mcp/servers.json"): `name`, `command`, `args`,
`transport`, `enabled`, `consumers`, `profile_path`.

`enabled` ships `false` — flips to `true` only once this module is
hardware-verified and `.disabled` is removed (CLAUDE.md §9).

## Separate browser profiles (task 4.9)

`consumers: ["agent"]` only — the `dev` consumer gets its own separate
Playwright MCP registration from `dev-ai-mcp-dev-servers` (name
`playwright`, npx-per-run with no persistent profile). This entry's
`command`/`args` invoke the globally-installed `playwright-mcp` binary
with `--user-data-dir /var/lib/aipc-agent/browser-profile`
(`profile_path` in the registry entry too), so the agent's browser
session never shares cookies/storage state with a developer's manual
Playwright MCP use. `post-install.sh` creates that profile directory
(`install -d -m 0700`) at build time.

## Status

Static + render-verified only (2026-07-06) — see verification tiers,
CLAUDE.md §9. `.disabled`: no hardware verification yet of the actual
Playwright MCP round trip through a real `node` distrobox on the
physical machine.

## Dependencies
- dev-distrobox-templates (Node template + the distrobox itself)
- dev-ai-mcp-dev-servers (sibling `dev`-consumer playwright entry)
- llm-litellm

## Spec
openspec/changes/phase-4-agent — tasks 1.3, 4.9, 6.3
