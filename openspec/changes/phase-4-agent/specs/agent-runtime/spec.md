## ADDED Requirements

### Requirement: Multi-Agent Supervisor With Four Shipped Sub-Agents

The `agent-orchestrator` module SHALL provide a LangGraph supervisor
graph and four sub-agent graphs: Researcher, Coder, Browser, and Daily
Assistant. The supervisor SHALL be able to dispatch sub-agents in
parallel and merge their results. Each sub-agent SHALL have a default
LiteLLM model alias bound at graph-construction time and SHALL NOT
hard-code provider URLs or backend ports.

Default model bindings:

| Role             | Default alias    |
|------------------|------------------|
| Supervisor       | `main-70b`       |
| Researcher       | `coder-fast`     |
| Coder            | `coder-strong`   |
| Browser          | `vlm-qwen2vl`    |
| Daily Assistant  | `intent-3b`      |

#### Scenario: All four sub-agent graphs constructible

- **WHEN** `python -c "from aipc_agent.graphs import supervisor, researcher, coder, browser, daily_assistant; [g() for g in (supervisor, researcher, coder, browser, daily_assistant)]"` is run
- **THEN** the command exits 0 and every graph compiles without raising

#### Scenario: Supervisor can fan out to two sub-agents in parallel

- **WHEN** the supervisor is given a task that decomposes into a search
  step and a code-edit step
- **THEN** the LangGraph trace shows Researcher and Coder nodes
  invoked concurrently (not strictly sequenced) and the supervisor
  merges both results before responding

#### Scenario: Each sub-agent uses its declared default model

- **WHEN** a sub-agent makes its first LLM call after construction with
  no per-call override
- **THEN** the request to `http://127.0.0.1:4000/v1/chat/completions`
  carries `"model": "<the alias from the table above>"`

---

### Requirement: LangGraph Is The Only Agent Framework

Every agent loop in the `agent-runtime` capability SHALL be implemented
on LangGraph. No module under `modules/agent-*/` SHALL import a
competing agent framework (Pydantic AI, OpenAI Agents SDK, AutoGen,
CrewAI, hand-rolled supervisor loops). State checkpointing SHALL use
LangGraph's built-in sqlite checkpointer; the checkpoint file SHALL
live under `/var/lib/aipc-agent/checkpoints/`.

#### Scenario: No competing framework imported

- **WHEN** `grep -rE '^(import|from) (pydantic_ai|openai_agents|autogen|crewai)\\b' modules/agent-*/` is run
- **THEN** the command exits non-zero (no matches found)

#### Scenario: Crashed task resumes from checkpoint

- **WHEN** a Coder sub-agent task is running, the orchestrator process
  is killed mid-task, restarted, and the user runs `aipc agent resume <task-id>`
- **THEN** the task continues from the last LangGraph checkpoint
  rather than restarting from step 0

---

### Requirement: LiteLLM Is The Only LLM Endpoint Any Agent Talks To

Every LLM call from any `agent-*` module SHALL go to
`http://127.0.0.1:4000` (the Phase 1 LiteLLM gateway). No `agent-*`
module SHALL declare a direct backend URL (Ollama on `:11434`,
Lemonade on `:8001`, vLLM on `:8000`, or any cloud provider URL such
as `api.openai.com`, `api.anthropic.com`,
`generativelanguage.googleapis.com`). This requirement cross-references
`CLAUDE.md §7`.

#### Scenario: No direct backend URL in any agent module config

- **WHEN** `grep -rE '(api\\.openai\\.com|api\\.anthropic\\.com|generativelanguage\\.googleapis\\.com|127\\.0\\.0\\.1:(11434|8001|8000))' modules/agent-*/files/ modules/agent-*/env/` is run
- **THEN** the command exits non-zero (no matches found)

#### Scenario: Sub-agent LLM call hits the gateway

- **WHEN** any sub-agent makes an LLM call and the LiteLLM gateway is
  active
- **THEN** the request appears in the LiteLLM access log at
  `127.0.0.1:4000`, not in any backend's direct access log

---

### Requirement: Code Execution Runs In A Sandboxed Distrobox Container

The `agent-code-shell` module SHALL execute Open Interpreter actions
exclusively inside a distrobox container declared by
`/etc/aipc/distrobox/templates/agent-runtime.yaml`. The container SHALL
mount only an explicit allowlist of host paths (declared in the
template) and SHALL NOT mount `$HOME` by default. Direct shell-out to
the host from `agent-code-shell` SHALL be a verify-time failure.

#### Scenario: agent-runtime template ships and assembles

- **WHEN** `distrobox assemble create --file /etc/aipc/distrobox/templates/agent-runtime.yaml` is run on a fresh image
- **THEN** the command exits 0 and `distrobox enter agent-runtime -- which interpreter` succeeds

#### Scenario: Default mount set excludes $HOME

- **WHEN** `distrobox enter agent-runtime -- ls /host-home` is run on
  a fresh image with no user-added mounts
- **THEN** the command exits non-zero (no such path) — the user's
  `$HOME` is not visible inside the agent container

#### Scenario: agent-code-shell does not bypass the sandbox

- **WHEN** `grep -rE 'subprocess\\.(run|Popen|check_(call|output))\\(' modules/agent-code-shell/` is run
- **THEN** every match either invokes `distrobox enter agent-runtime --`
  or is inside a clearly-marked sandbox-bootstrap helper (verified by
  reviewer note)

---

### Requirement: Browser Sub-Agent Uses Playwright MCP Server

The `agent-browser` module SHALL install Playwright MCP and register
it in the shared MCP registry (`/etc/aipc/mcp/servers.json`). The
Browser sub-agent SHALL connect to that MCP server entry and SHALL
NOT speak the Chrome DevTools Protocol directly or embed a custom
browser-control library. When DOM-only navigation cannot complete a
task, the Browser sub-agent MAY layer `vlm-qwen2vl` (via LiteLLM) on
top of Playwright MCP screenshots to reason about layout.

#### Scenario: Playwright MCP registered in the shared registry

- **WHEN** `jq '.servers[] | select(.name=="playwright")' /etc/aipc/mcp/servers.json` is run
- **THEN** the output contains a non-empty entry with a `command` field
  pointing at the Playwright MCP server binary

#### Scenario: Browser sub-agent does not use browser-use or CDP directly

- **WHEN** `grep -rE '^(import|from) (browser_use|pychrome|playwright)\\b' modules/agent-browser/` is run
- **THEN** no `browser_use` or `pychrome` import is matched (Playwright
  imports are allowed only inside the MCP server's own package, not
  from sub-agent code)

---

### Requirement: Screen Control Has Session-Gate Default And Always-On Opt-In

The `agent-screen-control` module SHALL ship two operation modes, both
brokered by the `aipc-agent-gate` daemon:

1. **session-gate (default)**: time-bounded grant. The agent has no
   screen access until the user runs
   `aipc agent screen --mode session <duration>`. The grant expires
   automatically.
2. **always-on (opt-in)**: persistent grant with a window-class
   blacklist. Windows matching the blacklist SHALL be excluded from
   VLM input capture AND from xdotool/ydotool input delivery. The
   blacklist file lives at
   `/etc/aipc/agent-gate/screen-blacklist.conf` and SHALL ship with a
   default set covering password managers, GNOME Keyring, and SSH
   terminals.

The default mode SHALL be session-gate. Always-on SHALL require an
explicit `aipc agent screen --mode always` invocation.

#### Scenario: No screen access without an active grant

- **WHEN** the image is freshly deployed, no `aipc agent screen` command
  has been run, and a sub-agent attempts a screen-control tool call
- **THEN** the tool call returns a "no active screen grant" error and
  is logged by `aipc-agent-gate`

#### Scenario: Session grant expires automatically

- **WHEN** the user runs `aipc agent screen --mode session 1m` and 90
  seconds elapse with no further command
- **THEN** `aipc agent gate status` reports no active screen grant and
  subsequent screen-control tool calls fail closed

#### Scenario: Always-on mode hides blacklisted windows

- **WHEN** always-on mode is active, a window with class `1Password` is
  focused, and a sub-agent requests a screenshot
- **THEN** the returned screenshot has the 1Password window region
  blanked or excluded, and `xdotool`/`ydotool` delivery into the
  1Password window class is refused

#### Scenario: Default blacklist ships

- **WHEN** the image is freshly deployed
- **THEN** `/etc/aipc/agent-gate/screen-blacklist.conf` exists and
  contains entries matching at least `1Password`, `GNOME Keyring`, and
  `gnome-terminal-server` (or the SSH-terminal class equivalent in
  bazzite-dx)

---

### Requirement: Risky Actions Require A Permission Grant Via aipc-agent-gate

The `aipc-agent-gate.service` daemon SHALL broker grants for the
following risky action classes: `file-delete` (deletion outside the
agent workspace), `git-push`, `package-install` (host dnf or any
distrobox package manager), `email-send`, and `cloud-api` (any LLM or
tool call that incurs cost outside the local box). Grants SHALL be
scoped either:

- **session**: time-bounded (default 30 minutes), specified by
  `aipc agent gate grant --scope session <duration> --actions <list>`.
- **task**: bounded to a single supervisor task id, specified by
  `aipc agent gate grant --scope task <task-id> --actions <list>`;
  auto-revoked when the supervisor marks the task done.

The orchestrator and every sub-agent SHALL check with the gate before
performing any action in those classes; absence of a matching active
grant SHALL fail the action closed.

#### Scenario: file-delete outside workspace is denied without grant

- **WHEN** the Coder sub-agent attempts to delete a file outside the
  agent workspace mount and no `file-delete` grant is active
- **THEN** the action is refused, the gate logs a deny entry, and the
  sub-agent receives a "permission denied" tool error

#### Scenario: per-task grant auto-revokes when task completes

- **WHEN** the user grants
  `aipc agent gate grant --scope task <id> --actions email-send`,
  the supervisor reports the task done, and the gate runs its
  post-task hook
- **THEN** `aipc agent gate status` no longer lists the grant and any
  subsequent `email-send` from any sub-agent is refused

#### Scenario: session grant covers all listed actions until expiry

- **WHEN** the user grants
  `aipc agent gate grant --scope session 30m --actions file-delete,git-push`
  and 10 minutes later the Coder sub-agent attempts both actions
- **THEN** both actions succeed (the gate returns a positive
  authorisation for each) and the log records the use against the
  active session grant

---

### Requirement: Shared MCP Registry At /etc/aipc/mcp/servers.json

The `agent-mcp-gateway` module SHALL provide a single config file at
`/etc/aipc/mcp/servers.json` containing the registry of MCP servers
installed on the host. The file SHALL be JSON; the schema SHALL be
declared in the module README and SHALL include at minimum, per
server: `name`, `command`, `args` (array), `transport` (`stdio` |
`sse`), `enabled` (boolean), and `consumers` (array of consumer tags,
e.g. `agent`, `dev`). Every MCP-aware client on the host (Phase 4
sub-agents AND Phase 6 dev tools) SHALL read this file as its source
of truth for MCP server discovery. `agent-mcp-gateway` SHALL NOT
itself be a daemon and SHALL NOT proxy MCP traffic.

#### Scenario: Registry file present and parseable

- **WHEN** the image is freshly deployed
- **THEN** `/etc/aipc/mcp/servers.json` exists and `jq '.servers | length' /etc/aipc/mcp/servers.json` returns an integer ≥ 0

#### Scenario: Phase 6 dev MCP server registration uses this file

- **WHEN** Phase 6's `dev-ai-mcp-dev-servers` installs filesystem,
  github, and playwright MCP servers
- **THEN** all three appear as entries in
  `/etc/aipc/mcp/servers.json` (written by `dev-ai-mcp-dev-servers`,
  not by any daemon) with `consumers` including both `agent` and `dev`

#### Scenario: No MCP-proxy daemon ships

- **WHEN** the image is freshly deployed
- **THEN** `systemctl list-unit-files | grep -E 'mcp-(gateway|proxy)'`
  returns no enabled or active unit owned by `agent-mcp-gateway`

---

### Requirement: Voice-To-Agent Interface Is HTTP POST /chat

The `agent-orchestrator` module SHALL expose a FastAPI endpoint
`POST /chat` on `127.0.0.1:4100` (or the port declared in
`modules/agent-orchestrator/env/endpoint`). The request body SHALL be
JSON with fields `text` (string, required) and `session_id` (string,
optional). The response body SHALL be JSON with fields `text`
(string) and `task_id` (string). Phase 3 Pipecat SHALL be the only
voice-side producer of requests to this endpoint. WebSocket streaming
is not in this change (v2).

#### Scenario: /chat round-trip works

- **WHEN** `curl -sS -X POST http://127.0.0.1:4100/chat -H 'content-type: application/json' -d '{"text":"hello"}'` is run
- **THEN** the response is HTTP 200 with a JSON body containing
  `text` and `task_id` fields

#### Scenario: Endpoint is loopback-only

- **WHEN** `ss -tlnp | grep ':4100'` is run on the host
- **THEN** the listening address is `127.0.0.1:4100` (not `0.0.0.0:4100`)

#### Scenario: No websocket route shipped yet

- **WHEN** `curl -sS -i -H 'Upgrade: websocket' -H 'Connection: Upgrade' http://127.0.0.1:4100/chat` is run
- **THEN** the response is HTTP 4xx or 5xx — the websocket upgrade is
  not honoured in this version

---

### Requirement: Health Check Covers All agent-runtime Modules

`aipc doctor` SHALL execute `verify.sh` for each of the eight
agent-runtime modules and report per-module OK/FAIL/OPTIONAL status.
The orchestrator liveness check SHALL include `GET /chat` (as a HEAD
or OPTIONS) returning a non-5xx response. The MCP registry check SHALL
parse `/etc/aipc/mcp/servers.json` with `jq` and fail loudly on schema
violations. `aipc doctor` SHALL exit 0 only when all non-optional
agent-runtime modules report OK.

#### Scenario: All modules OK on a fully-deployed Phase 4 image

- **WHEN** `aipc doctor` runs on a host with all eight agent-runtime
  modules installed and the agent-runtime distrobox assembled
- **THEN** the output table shows OK for `agent-orchestrator`,
  `agent-code-shell`, `agent-browser`, `agent-screen-control`,
  `agent-tools-files`, `agent-tools-calendar`, `agent-tools-search`,
  and `agent-mcp-gateway`; the process exits 0

#### Scenario: MCP registry schema violation is reported

- **WHEN** `/etc/aipc/mcp/servers.json` is malformed (missing
  required field or invalid JSON)
- **THEN** `aipc doctor` prints FAIL for `agent-mcp-gateway` with a
  one-line diagnosis naming the schema violation and exits non-zero
