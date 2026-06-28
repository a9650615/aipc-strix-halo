## Context

The AI PC is a developer workstation first and an assistant second. The
host image must ship a working IDE + AI coding stack the user can open on
firstboot and start working in, without `dnf install` chores. Every AI
coding tool the user might prefer is preinstalled; the user picks by
trying, because switching cost is zero when every tool points at the same
LiteLLM gateway.

The image is immutable (`bazzite-dx`-derived bootc), already 5+ GiB. The
six AI coding tools add tens of MiB combined — the storage cost of
preinstalling everything is negligible against the UX cost of "go install
your editor before you can work".

## Goals / Non-Goals

**Goals:**

- Boot the AI PC, open Zed (or VSCode, or a terminal), and start coding
  with AI assistance against the local 70B in under a minute, no setup.
- All AI coding tools route through LiteLLM. Model swap = `models.yaml`
  edit, never per-tool config edit.
- `claude` (Anthropic CLI) is available and routes through LiteLLM via
  the Anthropic-compatible proxy surface.
- fish + starship + Ghostty match the user's existing Mac workflow so
  cross-machine muscle memory carries over.
- Per-stack distrobox templates (Node, Python) keep the host image clean
  of `npm install -g` and `pip install` sprawl.

**Non-Goals:**

- Bundling Neovim / LazyVim / Helix / Emacs. User has vim muscle memory;
  installing a curated Neovim distro is out of scope. `vim` is already
  in the base image.
- Go and Rust toolchains by default. Add later if an AI-PC use case
  needs them; YAGNI today.
- Postgres MCP server. Useful only once Phase 2 ships `db-postgres`;
  shipping it now means dead config.
- Per-user dotfile management (chezmoi, yadm). Defer to user discretion.
- AI-tool credential prebaking. Claude Code, OpenCode, and `gh` all
  require user-side login; the image ships the binaries and the env
  wiring, the user runs the login command once.

## Decisions

**D1 — Zed as primary editor, VSCode as secondary**

*Chosen:* Both ship. Zed is the default GUI editor (handler for
`text/plain`, `text/markdown`, source files). VSCode ships alongside,
exclusively as the host for the Continue and Cline extensions.

*Alternatives:*
- VSCode-only: drops Zed, loses native AI panel UX, but keeps the most
  mature AI-extension ecosystem.
- Zed-only: drops VSCode, loses Continue and Cline (neither has a Zed
  port as of 2026), keeps the image smaller.

*Why chosen:* User specified Zed primary, VSCode secondary. Zed's
built-in AI panel covers the dominant flow; the two extensions that have
no Zed port (Continue, Cline) live in VSCode as a side-car. Shipping
both costs ~150 MiB and zero ongoing maintenance.

**D2 — Six AI coding tools all preinstalled**

*Chosen:* Zed AI panel, Continue, Cline, Aider, Goose, OpenCode, and
Claude Code CLI all ship in the base image, all pre-pointed at
`http://127.0.0.1:4000`. The user picks favourites by trying.

*Alternatives:*
- Opt-in installer at firstboot: smaller image, but worse first
  impression — a fresh AI PC should be ready to code immediately.
- Ship only Continue + Aider (the canonical pair): cheaper, but the
  user explicitly asked for the full set so they can compare.

*Why chosen:* The image is already 5+ GiB; each AI tool is tens of MiB.
Switching cost between tools is zero because they all route through the
same gateway. Shipping the full set lets the user form an opinion
without `dnf install` friction.

**D3 — LiteLLM as the single LLM endpoint for all dev AI tools**

*Chosen:* Every AI coding tool's config file points at
`http://127.0.0.1:4000` (or the Anthropic-compat surface for `claude`).
Model names are the public API surface (`main-70b`, `coder-fast`,
`coder-strong`, `coder-thinking`).

*Alternatives:*
- Each tool talks to its preferred backend directly (Continue → Ollama,
  Aider → OpenAI, Claude Code → Anthropic): simplest at first, but
  every model swap becomes a per-tool config edit and every cost-control
  rule has to be re-implemented per tool.
- A second gateway specifically for dev tools: doubles the surface, no
  benefit — Phase 1 LiteLLM already does what's needed.

*Why chosen:* CLAUDE.md §7 makes this a project-wide constraint. One
gateway, one address, one place to change models, rate limits,
observability.

**D4 — Claude Code via LiteLLM Anthropic proxy**

*Chosen:* `ANTHROPIC_BASE_URL=http://127.0.0.1:4000` is set in
`/etc/profile.d/aipc-claude.sh` (or the equivalent fish vendor conf).
LiteLLM exposes an Anthropic-compatible surface alongside the
OpenAI-compatible one, so `claude` routes through the gateway. A
`main-cloud` alias backed by the real Anthropic key (via the
`cloud-llm-fallback` change) can be swapped in for `main-70b` by
editing `models.yaml`; the `claude` binary needs no client change.

*Alternatives:*
- Point `claude` directly at `api.anthropic.com`: loses local-first
  routing, loses the `models.yaml` swap-in-place pattern, fragments
  observability.
- Ship an open-source Claude Code clone (e.g., `aichat`, `crush`)
  instead: avoids closed-source concerns, but the user explicitly wants
  the real Anthropic CLI for parity with their other machines.

*Why chosen:* The whole point of D3 is one gateway. The Anthropic-compat
proxy is a few lines of LiteLLM config; using it keeps the contract
intact for the one tool that doesn't speak OpenAI by default.

**D5 — Node LTS + Python 3.12 distrobox templates; no Go, no Rust**

*Chosen:* Two YAML files under
`/etc/aipc/distrobox/templates/{node,python}.yaml` declaring the two
containers. `aipc dev up node` / `aipc dev up python` (or `distrobox
assemble` directly) materialises them on demand.

*Alternatives:*
- Add Go (for Ollama/k8s tooling) and Rust (for Zed dev, ripgrep-style
  tools): broader coverage out of the box, but the user explicitly
  scoped to Node + Python; adding two more containers means two more
  base images to keep current and two more attack surfaces.
- Ship one mega-container with everything: faster to spin up, but every
  rebuild rebuilds everything; per-language isolation is cleaner.

*Why chosen:* User explicit. Node covers OpenCode and Claude Code CLI
(both Node), plus the JS/TS dev surface. Python 3.12 covers `aipc`
itself, Aider, and the bulk of the AI-ecosystem libraries. Go and Rust
can be added in a follow-up change when a concrete need lands.

**D6 — fish + starship default shell, Ghostty default terminal**

*Chosen:* `chsh -s /usr/bin/fish` for the primary user account at image
build; starship prompt installed as a fish vendor conf; Ghostty
installed and registered as the default `x-scheme-handler/terminal`.

*Alternatives:*
- zsh + starship: bash-compatibility is better, but the user's syntax-
  highlighting + autosuggestion expectations are easier to satisfy with
  fish out of the box.
- Ptyxis (bazzite default): newer, less polished; Ghostty is what the
  user already runs on their Mac, so cross-machine consistency wins.

*Why chosen:* fish's defaults match the user's preferences without
plugin curation; Ghostty matches the user's existing terminal across
machines. Both are low-risk: bash and any other terminal remain
installable.

**D7 — MCP server set: Filesystem, GitHub, Playwright. Not Postgres.**

*Chosen:* Three MCP servers ship and register with the Phase 4
`agent-mcp-gateway`: filesystem (sandboxed to `~/`), GitHub (uses the
user's `gh auth` token at runtime), and Playwright (browser
automation).

*Alternatives:*
- Also Postgres: useful once Phase 2 ships `db-postgres`, dead config
  until then.
- Per-tool MCP config (one config in Goose, one in Cline, etc.): every
  MCP server addition becomes a fan-out edit.

*Why chosen:* Single registration point (Phase 4 gateway) means dev
tools and runtime agents share the same MCP registry. Adding Postgres
later is a one-line append to the gateway's config when Phase 2 lands.

**D8 — All dev MCP servers register with Phase 4 `agent-mcp-gateway`**

*Chosen:* `dev-ai-mcp-dev-servers` installs the three MCP binaries and
drops a registration manifest into the directory the Phase 4 gateway
watches. Dev tools (Goose, Cline, Claude Code) connect to the gateway,
not to individual MCP servers.

*Alternatives:*
- Each AI tool runs its own MCP client connecting to per-server
  endpoints: five places to update when an MCP server changes.
- Wait for Phase 4 before shipping MCP at all: blocks Phase 6 on Phase
  4; reasonable but unnecessary if we gate just the registration step.

*Why chosen:* CLAUDE.md §3 forbids per-tool sprawl. **Implication:**
group 6 tasks (MCP install + register) depend on Phase 4's
`agent-mcp-gateway` module shape being defined; until Phase 4 specs
land, those tasks are blocked. Documented as Open Question Q1.

**D9 — Claude Code and OpenCode require user-side authentication**

*Chosen:* Image installs the binaries (`@anthropic-ai/claude-code` via
npm into the Node distrobox; `opencode` via its installer into the same
distrobox) and ships the env wiring (`ANTHROPIC_BASE_URL` for Claude
Code, OpenCode's equivalent). The user runs `claude login` and
`opencode login` once at firstboot.

*Alternatives:*
- Prebake credentials via SOPS: works, but requires the user's API key
  before image build; coupling firstboot to a pre-shared secret is
  worse UX than a one-time login.
- Skip these two tools: drops the user's explicitly requested set.

*Why chosen:* CLAUDE.md §5 forbids baking secrets. The image ships
everything that doesn't depend on user credentials; a documented
firstboot checklist covers what does. Same model already used by `gh
auth login` and `git config user.email`.

**D10 — Module count stays at 10; shell+terminal fold into `dev-cli`,
Zed AI config folds into `dev-editors`**

*Chosen:* `dev-cli` owns the entire command-line environment (default
shell, default terminal, modern Unix CLI bundle). `dev-editors` owns
Zed + VSCode binaries + fonts + Zed's AI panel config. The six
standalone AI-tool modules are: `dev-ai-continue`,
`dev-ai-cline`, `dev-ai-aider`, `dev-ai-goose`, `dev-ai-opencode`,
`dev-ai-claude-code`. Plus `dev-distrobox-templates` and
`dev-ai-mcp-dev-servers`. Total: 10. Matches `docs/architecture.md §7`
header total (44).

*Alternatives:*
- Split `dev-shell`, `dev-terminal` from `dev-cli`: technically more
  "single purpose", but the cost is two more module READMEs, two more
  `verify.sh` files, and an updated 44-module total in §7 — for what is
  one cohesive concern (command-line UX).
- Split `dev-ai-zed` from `dev-editors`: justifiable if Zed's AI config
  grew complex, but today it's a single config file under the Zed
  config directory. Continue and Cline get their own modules because
  they install a VSCode extension as well as configuring it; Zed's
  panel is built in, so the "module" would be a one-file config drop.

*Why chosen:* CLAUDE.md §8 "no abstractions you don't need". Folding
keeps the module count, README maintenance, and renderer surface
smaller. If either fold's contents grow over time, splitting is a
trivial follow-up change.

## Risks / Trade-offs

- **Default shell change**: `chsh` to fish for the primary user could
  surprise users who scripted around bash. **Mitigation**: bash remains
  installed and on `$PATH`; user can `chsh -s /usr/bin/bash` at any
  time.
- **Closed-source CLI dependencies**: Claude Code and OpenCode are
  vendor-controlled; their auth flow and binary distribution can
  change. **Mitigation**: install via the vendor-recommended channel
  (`npm i -g`), version-pin where possible, document firstboot login.
- **Phase 4 dependency for MCP**: `dev-ai-mcp-dev-servers` cannot
  fully ship until Phase 4 lands `agent-mcp-gateway`. **Mitigation**:
  gate group 6 tasks; ship Phase 6 modules 1–5 + 7–8 independently.
- **VSCode extension marketplace access**: Continue and Cline are
  installed via marketplace; reproducibility depends on the
  marketplace being reachable at image build. **Mitigation**: pin
  extension versions in `dev-ai-continue/files/` and
  `dev-ai-cline/files/`; vendor the `.vsix` if pinning proves flaky.
- **Distrobox + bootc interaction**: distrobox containers live under
  `~/.local/share/containers`; on a bootc-managed `/var` they survive
  image swaps, but no `aipc doctor` check confirms that today.
  **Mitigation**: add a doctor check that templates render and
  `distrobox assemble` succeeds in a dry-run.

## Migration Plan

No prior dev environment exists on this image. Phase 6 is net-new. The
only "migration" concern is the default-shell change: the primary user
account ships with fish from day zero, so no in-place migration is
needed for existing accounts (there are none).

## Open Questions

- **Q1 — Phase 4 `agent-mcp-gateway` not yet specced**:
  `dev-ai-mcp-dev-servers` registration (group 6 tasks) depends on the
  Phase 4 gateway's registration interface (file format, watch
  directory, expected MCP manifest schema). Two paths: write Phase 4
  next so Phase 6 group 6 can complete; or land Phase 6 groups 1–5 +
  7–8 first and pick up group 6 once Phase 4 lands. Recommend the
  latter — most of Phase 6 is independently useful and the MCP wiring
  is a 1–2 day follow-up once Phase 4 is clear.

- **Q2 — Default-shell change mechanism on bazzite-dx**: `chsh -s
  /usr/bin/fish` baked into the image works in theory; bazzite-dx may
  have its own user-creation flow that resets the shell. Needs
  validation on the first hardware build; fallback is a one-shot
  firstboot service that runs `chsh`.

- **Q3 — Anthropic Claude Code CLI distribution**: today's path is
  `npm install -g @anthropic-ai/claude-code` inside the Node distrobox.
  Alternative: standalone installer (`curl ... | sh`). Need to confirm
  on hardware which is more reliable inside a distrobox; both are
  user-side login regardless (D9).
