## Why

Phases 0–1 stood up the OS image and the LLM gateway; Phases 2–5 land
storage, voice, agents, and gaming. Phase 6 is the layer the user actually
touches when *writing* code on the box: editors, AI coding tools, shell,
terminal, and the per-stack distrobox containers that keep the host image
clean.

The architecture decision is that every AI coding tool talks to the same
LiteLLM gateway already shipped in Phase 1 — model swap-out is a
`models.yaml` edit, not a per-tool reconfiguration. Phase 6 puts that
contract into practice for six concrete tools (Zed, VSCode + Continue,
VSCode + Cline, Aider, Goose, OpenCode, Claude Code CLI).

## What Changes

- **New capability `dev-environment`** covering the 10 Phase 6 modules as
  one coherent host-side developer surface.
- **Editors**: Zed shipped as the primary editor, VSCode shipped as
  secondary (it hosts the Continue and Cline extensions, which have no
  Zed port today).
- **Six AI coding tools all preinstalled** and pre-wired to LiteLLM:
  Zed's native AI panel, Continue (VSCode), Cline (VSCode), Aider, Goose,
  OpenCode, and Anthropic's Claude Code CLI.
- **Claude Code via LiteLLM Anthropic proxy**: `ANTHROPIC_BASE_URL` is
  set to `http://127.0.0.1:4000` at the user-shell level, so `claude`
  routes through the gateway and `models.yaml` is the only place a swap
  between local Qwen and cloud Anthropic happens.
- **Shell / terminal / CLI bundle** folded into `dev-cli`: fish + starship
  as default user shell, Ghostty as default terminal, plus the modern
  Unix QoL set (mise, atuin, eza, bat, zoxide, gh, lazygit, git-delta,
  fzf, ripgrep, jq, yq, httpie).
- **Distrobox templates** for Node LTS and Python 3.12 only. No Go, no
  Rust by default.
- **MCP dev-servers** (Filesystem, GitHub, Playwright) installed and
  registered with the Phase 4 `agent-mcp-gateway`. Postgres MCP is
  deferred until Phase 2 lands `db-postgres`.
- **First-boot user actions** documented for the things the image cannot
  bake: Claude Code login, OpenCode login, `gh auth login`, and `git config
  user.{name,email}`.

## Capabilities

### New Capabilities

- `dev-environment`: Host-side developer surface — primary + secondary
  editors, six AI coding tools, default shell + terminal + CLI bundle,
  per-stack distrobox templates, and MCP dev-servers. All AI tools route
  to the Phase 1 LiteLLM gateway; the gateway is the only LLM endpoint
  any tool talks to.

### Modified Capabilities

- `ai-runtime` (Phase 1): No requirement changes. Phase 6 is a downstream
  consumer of the LiteLLM gateway contract from §7 of CLAUDE.md.

## Impact

- **`modules/`**: 10 new modules added (see tasks group 1). No existing
  module is touched.
- **`tools/aipc doctor`**: Gains per-tool config sanity checks (each AI
  tool's config file references `http://127.0.0.1:4000`).
- **`targets/bootc/Containerfile` + `targets/ansible/site.yml`**:
  Rendered outputs grow by 10 modules; both targets must reach the same
  end state.
- **Default user shell**: Changes from `bash` (bazzite-dx default) to
  `fish` for the primary user account; baked into the image.
- **Downstream consumers**: None — Phase 6 is itself the consumer.
- **Phase 4 dependency**: `dev-ai-mcp-dev-servers` registration step
  depends on `agent-mcp-gateway` being specced and shipped. Open question
  Q1 in `design.md`.
