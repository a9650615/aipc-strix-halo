## ADDED Requirements

### Requirement: Primary And Secondary Editors Both Ship

The `dev-editors` module SHALL install Zed as the primary GUI editor and
VSCode as the secondary GUI editor. Zed SHALL be configured as the
default handler for source files, `text/plain`, and `text/markdown`.
VSCode SHALL be present so the `dev-ai-continue` and `dev-ai-cline`
modules can install their VSCode extensions; VSCode has no
default-handler claim. Both editors SHALL be launchable from the GNOME
applications grid without further setup.

#### Scenario: Zed installed and is default text/source handler

- **WHEN** the image is freshly deployed
- **THEN** `which zed` returns a path under `/usr` and
  `xdg-mime query default text/plain` returns a Zed `.desktop` entry

#### Scenario: VSCode installed

- **WHEN** the image is freshly deployed
- **THEN** `which code` returns a path under `/usr` and
  `code --list-extensions` runs without error

#### Scenario: Zed AI panel pre-configured for LiteLLM

- **WHEN** a user opens Zed and invokes the AI panel
- **THEN** Zed's settings.json (under the user config dir, seeded from
  `dev-editors/files/`) declares `http://127.0.0.1:4000` as the
  OpenAI-compatible base URL with at least the `main-70b` model alias

---

### Requirement: Six AI Coding Tools Preinstalled

The image SHALL preinstall six AI coding tools, each configured to
route LLM requests through the Phase 1 LiteLLM gateway at
`http://127.0.0.1:4000`. The six tools are: Zed's native AI panel
(via `dev-editors`), Continue (VSCode extension, via `dev-ai-continue`),
Cline (VSCode extension, via `dev-ai-cline`), Aider CLI (via
`dev-ai-aider`), Goose CLI (via `dev-ai-goose`), OpenCode CLI (via
`dev-ai-opencode`), and Claude Code CLI (via `dev-ai-claude-code`).

#### Scenario: All six tools resolvable

- **WHEN** the image is freshly deployed and `aipc dev up node` and
  `aipc dev up python` have been run (for tools that live in
  distroboxes)
- **THEN** `code --list-extensions` includes `continue.continue` and
  `saoudrizwan.claude-dev` (Cline), `which aider` succeeds, `which
  goose` succeeds, `distrobox enter node -- which opencode` succeeds,
  and `distrobox enter node -- which claude` succeeds

#### Scenario: Each tool's config references the LiteLLM gateway

- **WHEN** `aipc doctor` runs the `dev-environment` checks
- **THEN** each of the six tools' config files contains the literal
  string `http://127.0.0.1:4000` (or, for Claude Code, the env file
  exports `ANTHROPIC_BASE_URL=http://127.0.0.1:4000`)

---

### Requirement: LiteLLM Is The Only LLM Endpoint Any Dev Tool Talks To

All dev-environment AI tool configurations SHALL declare the LiteLLM
gateway URL as the LLM endpoint. No dev-environment module SHALL
declare a direct backend URL (Ollama on `:11434`, Lemonade on `:8001`,
vLLM on `:8000`, or any cloud provider URL such as
`api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`).
This requirement cross-references `CLAUDE.md §7`.

#### Scenario: No direct backend URL in any dev module config

- **WHEN** `grep -rE
  '(api\\.openai\\.com|api\\.anthropic\\.com|generativelanguage\\.googleapis\\.com|127\\.0\\.0\\.1:(11434|8001|8000))'`
  is run against `modules/dev-*/files/`
- **THEN** the command exits non-zero (no matches found)

#### Scenario: LiteLLM gateway reachable from a dev tool's perspective

- **WHEN** `aipc doctor` runs and the LiteLLM gateway is active
- **THEN** a `GET http://127.0.0.1:4000/v1/models` from within the
  Node distrobox returns HTTP 200 and lists at least `main-70b`

---

### Requirement: Claude Code Routes Through LiteLLM Anthropic Proxy

The `dev-ai-claude-code` module SHALL set `ANTHROPIC_BASE_URL` to
`http://127.0.0.1:4000` in a system-wide profile drop-in readable by
both bash and fish. The LiteLLM gateway SHALL expose an
Anthropic-compatible API surface at the same address. Swapping between
a local backend (`main-70b` via Ollama) and the real Anthropic API
(`main-cloud` via the `cloud-llm-fallback` change) SHALL be possible by
editing only `models.yaml` plus restarting the LiteLLM gateway; the
`claude` binary SHALL require no client-side reconfiguration.

#### Scenario: ANTHROPIC_BASE_URL exported in every login shell

- **WHEN** a user opens a new fish or bash login shell
- **THEN** `echo $ANTHROPIC_BASE_URL` prints `http://127.0.0.1:4000`

#### Scenario: claude CLI reaches the gateway

- **WHEN** `claude --version` is run in the Node distrobox with the
  user's `claude login` completed
- **THEN** the command exits 0 and any subsequent `claude` invocation
  reaches `127.0.0.1:4000`, not `api.anthropic.com` (verifiable by
  inspecting LiteLLM access logs)

---

### Requirement: Distrobox Templates Cover Node LTS And Python 3.12

The `dev-distrobox-templates` module SHALL install two distrobox
template YAML files under `/etc/aipc/distrobox/templates/`: `node.yaml`
(declaring a Node LTS container) and `python.yaml` (declaring a Python
3.12 container). No other template SHALL ship by default. Both
templates SHALL be assembleable by running `distrobox assemble create
--file <template>.yaml` without modification.

#### Scenario: Node template assembles cleanly

- **WHEN** `distrobox assemble create --file
  /etc/aipc/distrobox/templates/node.yaml` is run on a fresh image
- **THEN** the command exits 0 and `distrobox enter node -- node
  --version` prints a Node LTS version

#### Scenario: Python template assembles cleanly

- **WHEN** `distrobox assemble create --file
  /etc/aipc/distrobox/templates/python.yaml` is run on a fresh image
- **THEN** the command exits 0 and `distrobox enter python -- python3
  --version` prints `Python 3.12.x`

#### Scenario: No Go or Rust template ships

- **WHEN** `ls /etc/aipc/distrobox/templates/` is run on a fresh image
- **THEN** the output contains only `node.yaml` and `python.yaml`

---

### Requirement: Default Shell Is Fish, Default Terminal Is Ghostty, CLI Bundle Present

The `dev-cli` module SHALL install fish as the default login shell for
the primary user account, install starship as fish's prompt via a
vendor configuration file, install Ghostty and register it as the
default `x-scheme-handler/terminal`, and install the modern Unix CLI
bundle: `mise`, `atuin`, `eza`, `bat`, `zoxide`, `gh`, `lazygit`,
`git-delta`, `fzf`, `ripgrep`, `jq`, `yq`, and `httpie`. `bash` SHALL
remain installed and switchable via `chsh`.

#### Scenario: Primary user's default shell is fish

- **WHEN** `getent passwd $(id -un 1000)` is run on a fresh image
- **THEN** the seventh colon-separated field is `/usr/bin/fish`

#### Scenario: Ghostty is the default terminal handler

- **WHEN** `xdg-settings get default-terminal-emulator` (or equivalent
  `gsettings` query) is run
- **THEN** the returned `.desktop` entry resolves to Ghostty

#### Scenario: Every CLI bundle binary is on PATH

- **WHEN** `command -v` is run for each of `fish`, `starship`, `mise`,
  `atuin`, `eza`, `bat`, `zoxide`, `gh`, `lazygit`, `delta`, `fzf`,
  `rg`, `jq`, `yq`, `http`, `ghostty`
- **THEN** every invocation prints a path under `/usr` and exits 0

---

### Requirement: MCP Dev Servers Installed And Registered With Phase 4 Gateway

The `dev-ai-mcp-dev-servers` module SHALL install three MCP servers
(Filesystem, GitHub, Playwright) and register them with the Phase 4
`agent-mcp-gateway`. Dev tools (Goose, Cline, Claude Code) SHALL
connect to the gateway, not to individual MCP servers. The Filesystem
server SHALL be sandboxed to `$HOME`. The GitHub server SHALL use the
user's `gh auth` token at runtime. No Postgres MCP server SHALL ship
in this change (deferred until Phase 2 `db-postgres`).

#### Scenario: Three MCP server binaries installed

- **WHEN** the image is freshly deployed
- **THEN** the three MCP servers (filesystem, github, playwright) are
  installed under the locations the Phase 4 gateway expects (path
  defined by `agent-mcp-gateway`)

#### Scenario: Registration manifest present for the Phase 4 gateway

- **WHEN** `aipc doctor` runs the dev-environment checks
- **THEN** a manifest at the path watched by `agent-mcp-gateway`
  declares the three MCP servers, their command lines, and their
  sandbox / token policies

#### Scenario: Postgres MCP server is not present

- **WHEN** `ls` is run against the MCP server install directory
- **THEN** the listing does not include a `postgres` entry; the
  registration manifest does not declare a postgres MCP server

---

### Requirement: First-Boot User Configuration Documented

The image SHALL NOT bake any user-side credentials. The
`dev-environment` modules SHALL document the firstboot user actions
required to make the AI coding stack fully functional: `claude login`
(Claude Code CLI), `opencode login` (OpenCode CLI), `gh auth login`
(GitHub MCP token + gh CLI), and `git config --global
user.{name,email}`. Documentation SHALL live in the respective module
READMEs and SHALL be surfaced by `aipc doctor` as informational
(non-failing) when the corresponding credentials are absent.

#### Scenario: aipc doctor flags missing user credentials as INFO

- **WHEN** `aipc doctor` runs on a freshly deployed image with no user
  logins yet completed
- **THEN** the dev-environment section reports INFO (not FAIL) for the
  Claude Code, OpenCode, and GitHub-MCP credential checks, with a
  one-line hint naming the login command

#### Scenario: No baked secrets in any dev module

- **WHEN** `grep -rE
  '(sk-ant-|sk-proj-|ghp_|gho_|ghs_)' modules/dev-*/` is run
- **THEN** the command exits non-zero (no matches found)
