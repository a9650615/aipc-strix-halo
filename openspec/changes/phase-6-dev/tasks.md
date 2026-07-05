## 1. Module Scaffolding (10 modules)

> Status 2026-07-01: 9 of 10 modules scaffolded, enabled, and CI-build-green
> (commit `a9aceb1` + opus dedup `00d0d5a`). The shipped form is simpler than
> the per-task detail below: shared CLI tools (git-delta/fzf/ripgrep/jq/yq/
> httpie) live in `system-base`, not dev-cli; editors install at runtime via
> Flatpak; lazygit/starship/ghostty/mise/atuin are documented manual installs
> (not in bazzite-dx repos). AI-tool installs (claude-code, aider, opencode,
> goose, extensions) run at first launch, not build time.

- [x] 1.1 `dev-cli`: create `modules/dev-cli/` with README, packages.txt
  (fish, starship, ghostty, mise, atuin, eza, bat, zoxide, gh, lazygit,
  git-delta, fzf, ripgrep, jq, yq, httpie), post-install.sh (chsh fish
  for uid 1000, register ghostty as default terminal handler, drop
  starship vendor conf into fish), verify.sh (binaries on PATH +
  default shell check + default terminal handler check).
  **Shipped**: packages deduped to `fish gh zoxide bat eza
  jetbrains-mono-fonts fira-code-fonts` (shared tools in `system-base`;
  starship/lazygit/ghostty/mise/atuin → manual install per README).
  post-install = `chsh -s fish`. ghostty terminal-handler registration
  deferred (ghostty itself is a manual install).
- [x] 1.2 `dev-editors`: create `modules/dev-editors/` with README,
  packages.txt (zed, code, JetBrains Mono Nerd Font or equivalent),
  files/ for Zed AI panel config (`~/.config/zed/settings.json` seeded
  with LiteLLM base URL + model aliases), post-install.sh (register
  Zed as default text/source handler), verify.sh (both editors
  installed, Zed config present and references `127.0.0.1:4000`).
  **Shipped**: no rpm packages (VSCode/Zed are runtime Flatpaks; fonts
  declared in dev-cli). Zed `settings.json` seed config shipped under
  `etc/skel/.config/zed/`. Zed-as-default-handler registration deferred
  to runtime (no editor present at build).
- [x] 1.3 `dev-distrobox-templates`: create
  `modules/dev-distrobox-templates/` with README, files/ containing
  `etc/aipc/distrobox/templates/{node,python}.yaml`, post-install.sh
  (no-op, files-only), verify.sh (both YAML files exist and parse).
  **Shipped** (templates renamed `.yaml`→`.ini` in `4cde9b5` — they are
  distrobox-assemble INI syntax, not YAML).
  **2026-07-06 catch-up fix**: `post-install.sh` still contained a dead
  copy-loop from before the `.yaml`→`.ini` rename — it referenced
  `node.yaml`/`python.yaml` from a `/usr/share/aipc/dev-distrobox-templates`
  staging dir this module never populates (the renderer's
  `COPY modules/.../files/ /` step already stages `node.ini`/`python.ini`
  directly at `/etc/aipc/distrobox/`). The loop's `[ -f ]` guard always
  failed so it was a silent no-op, not a live bug, but misleading;
  replaced with a real no-op + comment. Also note: `verify.sh` is still
  the generic disabled-marker stub — it does not actually check the two
  `.ini` files exist/parse as the original task text promised. Tracked
  correctly already under §7 (aipc doctor extensions, not implemented),
  not re-flagged here as a new gap.
- [x] 1.4 `dev-ai-continue`: create `modules/dev-ai-continue/` with
  README, post-install.sh (`code --install-extension continue.continue
  --force` for uid 1000), files/ for the Continue config pointing at
  `127.0.0.1:4000`, verify.sh (extension installed + config references
  gateway).
  **Shipped**: config at `etc/skel/.continue/config.yaml` (gateway-ref
  confirmed). Extension install moved to runtime (build-time
  `code --install-extension` is a network call).
- [x] 1.5 `dev-ai-cline`: create `modules/dev-ai-cline/` with README,
  post-install.sh (`code --install-extension saoudrizwan.claude-dev
  --force`), files/ for the Cline config pointing at gateway,
  verify.sh.
  **Shipped**: config at `etc/skel/.config/cline/config.yaml`. Extension
  install moved to runtime.
- [x] 1.6 `dev-ai-aider`: create `modules/dev-ai-aider/` with README,
  packages.txt or post-install.sh installing `aider-chat` into the
  Python distrobox via pipx, files/ for `~/.aider.conf.yml` pointing
  at gateway, verify.sh.
  **Shipped**: packages=`pipx`; config at `etc/skel/.aider.conf.yml`
  (gateway-ref confirmed). aider-chat itself installs via pipx at
  runtime in the python distrobox.
- [x] 1.7 `dev-ai-goose`: create `modules/dev-ai-goose/` with README,
  post-install.sh installing goose CLI, files/ for goose config
  pointing at gateway with MCP gateway endpoint, verify.sh.
  **Shipped**: config at `etc/skel/.config/goose/profiles.yaml`
  (gateway-ref confirmed). goose CLI install is runtime (upstream
  installer script, documented in README).
- [x] 1.8 `dev-ai-opencode`: create `modules/dev-ai-opencode/` with
  README, post-install.sh installing `opencode` into the Node
  distrobox (`distrobox enter node -- npm i -g opencode` or
  vendor-recommended installer), files/ for opencode config pointing
  at gateway, verify.sh.
  **Shipped**: config at `etc/skel/.config/opencode/config.json`
  (gateway-ref confirmed). opencode installs at runtime in the node
  distrobox.
- [x] 1.9 `dev-ai-claude-code`: create `modules/dev-ai-claude-code/`
  with README, post-install.sh installing `@anthropic-ai/claude-code`
  into the Node distrobox, files/ for
  `/etc/profile.d/aipc-claude.sh` and matching fish vendor conf
  exporting `ANTHROPIC_BASE_URL=http://127.0.0.1:4000`, verify.sh
  (binary present + env var exported in both bash and fish).
  **Shipped**: config at `etc/skel/.claude/settings.json` (gateway-ref
  confirmed) + `etc/aipc/env.d`-style wiring. claude-code binary
  installs at runtime in the node distrobox. (Note: gateway routing
  shipped via skel settings.json rather than `/etc/profile.d` env —
  see 3.4.)
- [ ] 1.10 `dev-ai-mcp-dev-servers`: create
  `modules/dev-ai-mcp-dev-servers/` with README, post-install.sh
  installing filesystem, github, playwright MCP servers, files/ for
  the registration manifest at the path the Phase 4 gateway watches,
  verify.sh (three binaries present + manifest valid).
  **Deferred**: module scaffolded but `.disabled` — blocked on Phase 4
  `agent-mcp-gateway` (see section 6).
  **2026-07-06 real bug found+fixed**: `files/etc/aipc/mcp/servers.json`
  registered playwright as `@anthropic-ai/mcp-server-playwright`, a
  fictitious npm package (confirmed 404 against the npm registry
  2026-07-06) — same bug class as the fake-pip-package finding in
  phase-1/phase-2. Fixed to `@playwright/mcp` (Microsoft's real published
  package, confirmed on the registry). README's "What it does" also
  listed three different fictitious names
  (`@anthropic-ai/mcp-{filesystem,github,playwright}`) that didn't match
  either the fake or the real servers.json; rewritten to match the actual
  shipped manifest (`@modelcontextprotocol/server-filesystem`,
  `@modelcontextprotocol/server-github`, `@playwright/mcp`) and the actual
  manifest path (`/etc/aipc/mcp/servers.json`, README previously said
  `/etc/aipc/mcp-servers.d/dev-servers.yaml`). Module stays `.disabled`
  either way (blocked on Phase 4) — this fix only matters once it's
  unblocked, but would otherwise have shipped a broken default.

## 2. Editor AI Wiring

- [x] 2.1 Zed: write seed `settings.json` declaring
  `http://127.0.0.1:4000/v1` as the OpenAI base URL and model aliases
  `main-70b`, `coder-fast`, `coder-strong`, `coder-thinking`.
  **Shipped** at `dev-editors/files/etc/skel/.config/zed/settings.json`.
- [x] 2.2 Continue (`dev-ai-continue/files/`): write `~/.continue/config.yaml`
  or `config.json` per Continue's current schema, pointing all models
  at the LiteLLM gateway with the same alias set.
  **Shipped** at `etc/skel/.continue/config.yaml`.
- [x] 2.3 Cline (`dev-ai-cline/files/`): write VSCode workspace /
  global settings JSON declaring Cline's OpenAI-compatible provider as
  `http://127.0.0.1:4000` with the same alias set.
  **Shipped** at `etc/skel/.config/cline/config.yaml`.

## 3. CLI AI Tool Configs

- [x] 3.1 Aider (`dev-ai-aider/files/.aider.conf.yml`): declare
  `openai-api-base: http://127.0.0.1:4000` and default model
  `coder-strong`. **Shipped** (gateway-ref confirmed).
- [x] 3.2 Goose (`dev-ai-goose/files/`): declare LiteLLM provider and
  reference the Phase 4 MCP gateway endpoint for MCP discovery.
  **Shipped** (`etc/skel/.config/goose/profiles.yaml`); MCP-gateway
  endpoint resolves once Phase 4 lands.
- [x] 3.3 OpenCode (`dev-ai-opencode/files/`): declare LiteLLM as the
  provider per OpenCode's current schema. **Shipped**
  (`etc/skel/.config/opencode/config.json`).
- [ ] 3.4 Claude Code (`dev-ai-claude-code/files/`): drop
  `/etc/profile.d/aipc-claude.sh` exporting `ANTHROPIC_BASE_URL` and a
  matching `/etc/fish/conf.d/aipc-claude.fish` (fish does not source
  profile.d).
  **Partial**: gateway routing shipped via `etc/skel/.claude/settings.json`
  instead of profile.d/fish env exports. Functionally equivalent (routes
  to gateway) but different mechanism. Revisit if claude-code needs the
  env var outside its own settings.

## 4. Shell, Terminal, CLI Bundle

- [x] 4.1 `dev-cli/post-install.sh`: `chsh -s /usr/bin/fish` for the
  primary user account (uid 1000); idempotent. **Shipped**.
- [ ] 4.2 `dev-cli/files/etc/fish/conf.d/starship.fish`: enable
  starship prompt. **Deferred**: starship not in bazzite-dx repos →
  manual install (see dev-cli README); no vendor conf shipped.
- [ ] 4.3 `dev-cli/post-install.sh`: register Ghostty as default
  `x-scheme-handler/terminal` via `xdg-mime default` (run via
  systemd-firstboot or `pkexec`-equivalent if needed).
  **Deferred**: ghostty is a manual install (no rpm).
- [ ] 4.4 Confirm bazzite-dx's user-creation flow doesn't override the
  `chsh` (Open Question Q2 — needs hardware verification).

## 5. Distrobox Templates

- [x] 5.1 `dev-distrobox-templates/files/etc/aipc/distrobox/templates/node.yaml`:
  Node LTS container declaration (image, exported binaries, init
  hooks for `npm i -g @anthropic-ai/claude-code` and `opencode`).
  **Shipped** as `node.ini` (renamed `.yaml`→`.ini`, INI syntax).
- [x] 5.2 `dev-distrobox-templates/files/etc/aipc/distrobox/templates/python.yaml`:
  Python 3.12 container declaration (image, pipx, exported binaries).
  **Shipped** as `python.ini`.
- [ ] 5.3 (Optional) `aipc dev up <name>` wrapper around `distrobox
  assemble create --file /etc/aipc/distrobox/templates/<name>.yaml` —
  defer if `distrobox assemble` UX is acceptable as-is.

## 6. MCP Dev Servers (Blocked On Phase 4)

- [ ] 6.1 Install Filesystem MCP server (vendor-recommended path,
  sandboxed to `$HOME`). **Blocked on Phase 4.**
- [ ] 6.2 Install GitHub MCP server (uses `gh auth` token at runtime).
  **Blocked on Phase 4.**
- [ ] 6.3 Install Playwright MCP server. **Blocked on Phase 4.**
- [ ] 6.4 Write registration manifest at the path declared by Phase 4
  `agent-mcp-gateway`. **BLOCKED**: requires Phase 4 spec to land.
- [ ] 6.5 Confirm Goose, Cline, and Claude Code connect to the gateway
  (not direct MCP server endpoints). **BLOCKED on 6.4**.

## 7. aipc doctor Extensions

- [ ] 7.1 Add `dev-environment` section to `aipc doctor`: for each AI
  tool config file, assert it contains `http://127.0.0.1:4000`.
  **Not implemented** (doctor.py has no dev-environment section).
- [ ] 7.2 Add default-shell check: assert getent passwd for uid 1000
  has `/usr/bin/fish` as shell. **Not implemented**.
- [ ] 7.3 Add distrobox-template check: assert both YAML files exist
  and parse. **Not implemented**.
- [ ] 7.4 Add user-credential INFO checks (not FAIL): warn when
  `claude`/`opencode`/`gh` are unauthenticated, with the login command
  in the hint. **Not implemented**.
- [ ] 7.5 Add no-baked-secrets regression check: grep dev-* modules
  for known secret prefixes; fail loudly if any match. **Not implemented**.

## 8. Documentation

- [x] 8.1 Per-module README for each of the 10 modules: purpose,
  packages, files, dependencies, verify behaviour, firstboot user
  actions (where applicable). **Shipped** (all 10 modules have READMEs;
  dev-cli/dev-editors READMEs document the build/runtime split + manual
  installs).
- [ ] 8.2 `docs/firstboot-checklist.md` (or equivalent): consolidated
  user-side login checklist (`claude login`, `opencode login`, `gh
  auth login`, `git config --global user.{name,email}`).
  **Not written.**
- [x] 8.3 Confirm `docs/architecture.md §7` Phase 6 row matches the
  10-module list shipped here (no count change to the §7 header
  total).
  **2026-07-06**: found `dev-ai-opencode` was missing from the Phase 6
  table entirely (real omission — it was always one of the original 10,
  task 1.8, just never added to the doc). Added its row. Also fixed
  stale purpose text: `dev-cli` row still implied lazygit/mise/etc. ship
  in the image (they're manual installs per README §"Packages requiring
  manual install"); `dev-editors` row mentioned Neovim/LazyVim which was
  never actually scoped or shipped; `dev-distrobox-templates` row said
  "YAML" (renamed to INI in `4cde9b5`, see 1.3); `dev-ai-mcp-dev-servers`
  row listed "Postgres" (never in this module's scope) and didn't note
  it's disabled.
  **needs proposal**: a 12th module, `dev-ai-warp` (Warp terminal), was
  added 2026-07-03 outside this change's original 10-module scope (see
  `docs/agent-log.md` 2026-07-03 entry) and is enabled in the image today,
  but is **not** added to this table — doing so would bump the §7 header
  total past 45, which is a scope call for 大哥/an OpenSpec change, not a
  docs backfill. Flagging here instead of unilaterally deciding it.

## 9. Local Build Verification

- [x] 9.1 Run `tools/aipc render bootc`; confirm Containerfile
  includes all 10 dev-environment modules.
  **Done** — 10 of the 11 `dev-*` module dirs render (`dev-ai-warp`, added
  2026-07-03 outside this change's scope, also renders); only
  `dev-ai-mcp-dev-servers` stays `.disabled`. Re-verified 2026-07-06 after
  this catch-up pass's fixes: render-verified clean, no regression.
- [ ] 9.2 Run `tools/aipc render ansible --check`; confirm it lints
  clean.
  **Partial** — ansible renders + is valid YAML (re-confirmed 2026-07-06:
  `python3 -c "import yaml; yaml.safe_load(...)"` parses clean); yamllint
  itself is not installed in this sandbox so the "3 pre-existing style
  nits" claim from the 2026-07-01 pass could not be re-run today — static
  YAML-validity only, not a full yamllint pass.
- [ ] 9.3 Run each module's `verify.sh` in a privileged container
  against the built image; all non-optional modules exit 0 (group 6
  MCP register check stays OPTIONAL until Phase 4 lands).
  **Deferred** — requires the built image in a privileged container
  (hardware/CI-side).

## 10. AI PC Hardware Verification

- [ ] 10.1 Deploy `:rolling` tag to the AI PC via `bootc switch`.
- [ ] 10.2 Run `aipc doctor` on the AI PC; confirm dev-environment
  section all OK (or INFO for unfinished user logins).
- [ ] 10.3 Smoke-test each of the six AI tools: ask each to summarise
  a short file; confirm requests hit the LiteLLM gateway (check
  LiteLLM access logs) and not any direct backend or cloud API.
- [ ] 10.4 Confirm default shell on first login is fish, default
  terminal opens Ghostty.
- [ ] 10.5 Run `distrobox assemble create --file
  /etc/aipc/distrobox/node.ini` (path/extension corrected 2026-07-06 —
  templates renamed `.yaml`→`.ini` in `4cde9b5`, see 1.3) and confirm node
  container comes up and `claude` + `opencode` resolve.

> Section 10 is the user's hardware gate (CLAUDE.md §9) — not achievable
> from the build host.

## 11. Archive Change

- [ ] 11.1 Run `npx -y @fission-ai/openspec validate phase-6-dev
  --strict` — must print `Change 'phase-6-dev' is valid`.
- [ ] 11.2 Run `npx -y @fission-ai/openspec archive phase-6-dev` to
  merge the spec into `openspec/specs/dev-environment/spec.md` and
  close the change.

> Not ready to archive — sections 6 (blocked on Phase 4), 7 (doctor),
> 10 (hardware) remain open by design.

<!-- 2026-07-01 GLM5.2 bookkeeping pass: aligned checkboxes to shipped
     reality. Done: 1.1-1.9, 2.1-2.3, 3.1-3.3, 4.1, 5.1-5.2, 8.1, 9.1
     (~21/47). Open items are descoped (4.2/4.3), blocked-on-Phase-4
     (1.10/6.x), not-yet-implemented (7.x/8.2), or hardware (4.4/9.3/10.x).
     3.4 partial (skel settings.json vs profile.d). -->

<!-- 2026-07-06 claude-sonnet-5 catch-up pass (checked against real
     module files + docs/agent-log.md 2026-07-01/03/04/05 entries, same
     method as the phase-1/phase-2 catch-ups done earlier the same day):
     21/47 done (added 8.3). Two real bugs found+fixed (not just doc
     drift): (1) dev-ai-mcp-dev-servers/files/etc/aipc/mcp/servers.json
     registered a fictitious npm package for its playwright MCP server
     (@anthropic-ai/mcp-server-playwright, 404s against the real npm
     registry) -- fixed to the real @playwright/mcp; its README also
     listed three different fictitious package names and a stale manifest
     path, rewritten to match reality. (2) dev-distrobox-templates/
     post-install.sh carried dead code from before the .yaml->.ini rename
     (4cde9b5) that referenced a staging dir this module never populates
     -- always a silent no-op via its own [ -f ] guard, not a live bug,
     but misleading; replaced with a true no-op + explanatory comment.
     docs/architecture.md's Phase 6 table was missing dev-ai-opencode
     entirely (real omission, restored) and had stale purpose text for
     dev-cli/dev-editors/dev-distrobox-templates/dev-ai-mcp-dev-servers
     (fixed). Also fixed a stale node.yaml path reference in 10.5.
     needs-proposal: dev-ai-warp (added 2026-07-03, out of this change's
     original 10-module scope, enabled in the image today) is not added
     to architecture.md's Phase 6 table -- doing so bumps the §7 header
     module count past 45, a scope call left to 大哥/an OpenSpec change.
     Verification reached: static (pytest 115/115) + render-verified
     (bootc Containerfile + ansible playbook both render clean; ansible
     YAML validity confirmed via python yaml.safe_load, yamllint itself
     not installed in this sandbox so its "3 pre-existing style nits"
     claim from 2026-07-01 could not be re-run). No hardware access this
     session -- sections 4.4/9.3/10.x untouched, correctly still open. -->
