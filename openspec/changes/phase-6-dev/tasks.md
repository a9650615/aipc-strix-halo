## 1. Module Scaffolding (10 modules)

- [ ] 1.1 `dev-cli`: create `modules/dev-cli/` with README, packages.txt
  (fish, starship, ghostty, mise, atuin, eza, bat, zoxide, gh, lazygit,
  git-delta, fzf, ripgrep, jq, yq, httpie), post-install.sh (chsh fish
  for uid 1000, register ghostty as default terminal handler, drop
  starship vendor conf into fish), verify.sh (binaries on PATH +
  default shell check + default terminal handler check).
- [ ] 1.2 `dev-editors`: create `modules/dev-editors/` with README,
  packages.txt (zed, code, JetBrains Mono Nerd Font or equivalent),
  files/ for Zed AI panel config (`~/.config/zed/settings.json` seeded
  with LiteLLM base URL + model aliases), post-install.sh (register
  Zed as default text/source handler), verify.sh (both editors
  installed, Zed config present and references `127.0.0.1:4000`).
- [ ] 1.3 `dev-distrobox-templates`: create
  `modules/dev-distrobox-templates/` with README, files/ containing
  `etc/aipc/distrobox/templates/{node,python}.yaml`, post-install.sh
  (no-op, files-only), verify.sh (both YAML files exist and parse).
- [ ] 1.4 `dev-ai-continue`: create `modules/dev-ai-continue/` with
  README, post-install.sh (`code --install-extension continue.continue
  --force` for uid 1000), files/ for the Continue config pointing at
  `127.0.0.1:4000`, verify.sh (extension installed + config references
  gateway).
- [ ] 1.5 `dev-ai-cline`: create `modules/dev-ai-cline/` with README,
  post-install.sh (`code --install-extension saoudrizwan.claude-dev
  --force`), files/ for the Cline config pointing at gateway,
  verify.sh.
- [ ] 1.6 `dev-ai-aider`: create `modules/dev-ai-aider/` with README,
  packages.txt or post-install.sh installing `aider-chat` into the
  Python distrobox via pipx, files/ for `~/.aider.conf.yml` pointing
  at gateway, verify.sh.
- [ ] 1.7 `dev-ai-goose`: create `modules/dev-ai-goose/` with README,
  post-install.sh installing goose CLI, files/ for goose config
  pointing at gateway with MCP gateway endpoint, verify.sh.
- [ ] 1.8 `dev-ai-opencode`: create `modules/dev-ai-opencode/` with
  README, post-install.sh installing `opencode` into the Node
  distrobox (`distrobox enter node -- npm i -g opencode` or
  vendor-recommended installer), files/ for opencode config pointing
  at gateway, verify.sh.
- [ ] 1.9 `dev-ai-claude-code`: create `modules/dev-ai-claude-code/`
  with README, post-install.sh installing `@anthropic-ai/claude-code`
  into the Node distrobox, files/ for
  `/etc/profile.d/aipc-claude.sh` and matching fish vendor conf
  exporting `ANTHROPIC_BASE_URL=http://127.0.0.1:4000`, verify.sh
  (binary present + env var exported in both bash and fish).
- [ ] 1.10 `dev-ai-mcp-dev-servers`: create
  `modules/dev-ai-mcp-dev-servers/` with README, post-install.sh
  installing filesystem, github, playwright MCP servers, files/ for
  the registration manifest at the path the Phase 4 gateway watches,
  verify.sh (three binaries present + manifest valid).

## 2. Editor AI Wiring

- [ ] 2.1 Zed: write seed `settings.json` declaring
  `http://127.0.0.1:4000/v1` as the OpenAI base URL and model aliases
  `main-70b`, `coder-fast`, `coder-strong`, `coder-thinking`.
- [ ] 2.2 Continue (`dev-ai-continue/files/`): write `~/.continue/config.yaml`
  or `config.json` per Continue's current schema, pointing all models
  at the LiteLLM gateway with the same alias set.
- [ ] 2.3 Cline (`dev-ai-cline/files/`): write VSCode workspace /
  global settings JSON declaring Cline's OpenAI-compatible provider as
  `http://127.0.0.1:4000` with the same alias set.

## 3. CLI AI Tool Configs

- [ ] 3.1 Aider (`dev-ai-aider/files/.aider.conf.yml`): declare
  `openai-api-base: http://127.0.0.1:4000` and default model
  `coder-strong`.
- [ ] 3.2 Goose (`dev-ai-goose/files/`): declare LiteLLM provider and
  reference the Phase 4 MCP gateway endpoint for MCP discovery.
- [ ] 3.3 OpenCode (`dev-ai-opencode/files/`): declare LiteLLM as the
  provider per OpenCode's current schema.
- [ ] 3.4 Claude Code (`dev-ai-claude-code/files/`): drop
  `/etc/profile.d/aipc-claude.sh` exporting `ANTHROPIC_BASE_URL` and a
  matching `/etc/fish/conf.d/aipc-claude.fish` (fish does not source
  profile.d).

## 4. Shell, Terminal, CLI Bundle

- [ ] 4.1 `dev-cli/post-install.sh`: `chsh -s /usr/bin/fish` for the
  primary user account (uid 1000); idempotent.
- [ ] 4.2 `dev-cli/files/etc/fish/conf.d/starship.fish`: enable
  starship prompt.
- [ ] 4.3 `dev-cli/post-install.sh`: register Ghostty as default
  `x-scheme-handler/terminal` via `xdg-mime default` (run via
  systemd-firstboot or `pkexec`-equivalent if needed).
- [ ] 4.4 Confirm bazzite-dx's user-creation flow doesn't override the
  `chsh` (Open Question Q2 — needs hardware verification).

## 5. Distrobox Templates

- [ ] 5.1 `dev-distrobox-templates/files/etc/aipc/distrobox/templates/node.yaml`:
  Node LTS container declaration (image, exported binaries, init
  hooks for `npm i -g @anthropic-ai/claude-code` and `opencode`).
- [ ] 5.2 `dev-distrobox-templates/files/etc/aipc/distrobox/templates/python.yaml`:
  Python 3.12 container declaration (image, pipx, exported binaries).
- [ ] 5.3 (Optional) `aipc dev up <name>` wrapper around `distrobox
  assemble create --file /etc/aipc/distrobox/templates/<name>.yaml` —
  defer if `distrobox assemble` UX is acceptable as-is.

## 6. MCP Dev Servers (Blocked On Phase 4)

- [ ] 6.1 Install Filesystem MCP server (vendor-recommended path,
  sandboxed to `$HOME`).
- [ ] 6.2 Install GitHub MCP server (uses `gh auth` token at runtime).
- [ ] 6.3 Install Playwright MCP server.
- [ ] 6.4 Write registration manifest at the path declared by Phase 4
  `agent-mcp-gateway`. **BLOCKED**: requires Phase 4 spec to land.
- [ ] 6.5 Confirm Goose, Cline, and Claude Code connect to the gateway
  (not direct MCP server endpoints). **BLOCKED on 6.4**.

## 7. aipc doctor Extensions

- [ ] 7.1 Add `dev-environment` section to `aipc doctor`: for each AI
  tool config file, assert it contains `http://127.0.0.1:4000`.
- [ ] 7.2 Add default-shell check: assert getent passwd for uid 1000
  has `/usr/bin/fish` as shell.
- [ ] 7.3 Add distrobox-template check: assert both YAML files exist
  and parse.
- [ ] 7.4 Add user-credential INFO checks (not FAIL): warn when
  `claude`/`opencode`/`gh` are unauthenticated, with the login command
  in the hint.
- [ ] 7.5 Add no-baked-secrets regression check: grep dev-* modules
  for known secret prefixes; fail loudly if any match.

## 8. Documentation

- [ ] 8.1 Per-module README for each of the 10 modules: purpose,
  packages, files, dependencies, verify behaviour, firstboot user
  actions (where applicable).
- [ ] 8.2 `docs/firstboot-checklist.md` (or equivalent): consolidated
  user-side login checklist (`claude login`, `opencode login`, `gh
  auth login`, `git config --global user.{name,email}`).
- [ ] 8.3 Confirm `docs/architecture.md §7` Phase 6 row matches the
  10-module list shipped here (no count change to the §7 header
  total).

## 9. Local Build Verification

- [ ] 9.1 Run `tools/aipc render bootc`; confirm Containerfile
  includes all 10 dev-environment modules.
- [ ] 9.2 Run `tools/aipc render ansible --check`; confirm it lints
  clean.
- [ ] 9.3 Run each module's `verify.sh` in a privileged container
  against the built image; all non-optional modules exit 0 (group 6
  MCP register check stays OPTIONAL until Phase 4 lands).

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
  /etc/aipc/distrobox/templates/node.yaml` and confirm node container
  comes up and `claude` + `opencode` resolve.

## 11. Archive Change

- [ ] 11.1 Run `npx -y @fission-ai/openspec validate phase-6-dev
  --strict` — must print `Change 'phase-6-dev' is valid`.
- [ ] 11.2 Run `npx -y @fission-ai/openspec archive phase-6-dev` to
  merge the spec into `openspec/specs/dev-environment/spec.md` and
  close the change.
