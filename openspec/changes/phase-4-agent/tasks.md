## 1. Module Scaffolding (8 modules)

- [x] 1.1 `agent-orchestrator`: real, not just scaffolded —
  `aipc_agent/server.py` (FastAPI `/chat`) + `graphs.py` (supervisor)
  exist and are hardware-verified end-to-end (2026-07-05, see
  `docs/agent-log.md`: real `/chat` round trip through LiteLLM to
  ornith-35b, SELinux `name_connect` fix applied). Only the
  *supervisor* graph exists though — no sub-agent graphs (2.2-2.6
  below), matching its own verify.sh's documented "basic-skeleton
  scope" comment.
- [~] 1.2 `agent-code-shell`: distrobox template + packages.txt
  exist. **Missing the actual safety wrapper** — the file that's
  supposed to "always shell through `distrobox enter agent-runtime
  --`, refuse to run outside the sandbox" doesn't exist; verify.sh
  only checks `.disabled`. This is the security-relevant part of the
  task and wasn't done. Not attempted this pass — see note below.
- [~] 1.3 `agent-browser`: registry entry exists (fixed 2026-07-06:
  referenced a fictitious npm package `@anthropic-ai/mcp-server-playwright`
  — 404s — same bug class Phase 6 hit in `dev-ai-mcp-dev-servers`;
  corrected to the real `@playwright/mcp`). Missing: actual Playwright
  MCP install step in post-install.sh (currently just a comment saying
  it happens "distrobox-side at runtime" — no script that does it),
  verify.sh doesn't check binary presence.
- [~] 1.4 `agent-screen-control`: config (`screen-control.yaml`,
  mode + blacklist) and 2 of 4 spec'd packages (xdotool, ydotool —
  missing wmctrl and a Wayland screenshot tool) exist. **Missing
  entirely**: the execution wrapper that actually drives
  xdotool/ydotool, the Qwen2-VL screenshot bridge script, and any
  verify.sh check beyond `.disabled`. This is the most
  security-sensitive module in the repo (input injection +
  password-manager blacklist) — real implementation deliberately
  not attempted this pass, see note below.
- [~] 1.5 `agent-tools-files`: allowlist config exists. Missing the
  actual read/write/list/delete tool implementations and their
  allowlist enforcement.
- [~] 1.6 `agent-tools-calendar`: config stub exists (Google/Proton/
  Fastmail backend fields). Missing all three backends' actual logic
  and the `aipc agent oauth google` CLI.
- [~] 1.7 `agent-tools-search`: SearXNG quadlet + settings.yml are
  real and match the spec well. Missing: the tool wrapper that
  queries `127.0.0.1:8888` and parses JSON, and the Tavily opt-in path.
- [x] 1.8 `agent-mcp-gateway`: files-only, no daemon (matches spec).
  verify.sh validates `/etc/aipc/mcp/servers.json` is parseable JSON
  — reasonable minimum given task 1.8's own scope (schema
  documentation + empty seed, not a validator).

**Note on 1.2/1.4 (and Groups 2-5 below):** these are the actual
security-execution core of Phase 4 — sandboxed code execution,
input-injection screen control, the permission-gate audit/revoke
system. Auditing/fixing what already exists is one thing; writing the
part that decides "does this action get to run" is a different kind
of change (CLAUDE.md §10: security-sensitive default loosening).
Flagged for an explicit go/no-go from the user rather than
implemented opportunistically in an audit pass — see session report.

**Groups 2-9 status (2026-07-06 audit):** none of these are implemented
beyond what group 1 already covers (agent-orchestrator's supervisor graph
only; every other sub-agent graph, tool, and the entire permission-gate
system in Group 5 is unbuilt). This is a large, mostly security-sensitive
build (sandboxed code execution, screen-control input injection + audit
log, OAuth-backed calendar access) — CLAUDE.md §10 territory, not
something to implement opportunistically inside an audit pass. Left
untouched pending an explicit go/no-go + design pass from the user,
rather than guessed at. Groups 10-12 (build verification, hardware
verification, archive) are blocked on 2-9 landing first.

## 2. Agent Framework (LangGraph)

- [ ] 2.1 Pin `langgraph` and `langchain-litellm` versions in
  `agent-orchestrator/packages.txt` (no floating range).
- [ ] 2.2 Implement the supervisor graph: accepts `{text, session_id}`
  input, decomposes into sub-tasks, dispatches sub-agents (serial or
  parallel), merges outputs, returns `{text, task_id}`.
- [ ] 2.3 Implement Researcher sub-agent graph (default model
  `coder-fast`, tools: search.searxng, search.tavily, browser, files
  read).
- [ ] 2.4 Implement Coder sub-agent graph (default model
  `coder-strong`, tools: files read/write, agent-code-shell, git
  operations gated through `aipc-agent-gate`).
- [ ] 2.5 Implement Browser sub-agent graph (default model
  `vlm-qwen2vl`, tool: Playwright MCP only; VLM-on-screenshot
  fallback path).
- [ ] 2.6 Implement Daily Assistant sub-agent graph (default model
  `intent-3b`, tools: calendar, email, files read).
- [ ] 2.7 Configure LangGraph sqlite checkpointer at
  `/var/lib/aipc-agent/checkpoints/`; write `aipc agent resume
  <task-id>` CLI.

## 3. Sandbox + Code Execution

- [ ] 3.1 Write `/etc/aipc/distrobox/templates/agent-runtime.yaml`
  (Fedora 41 base, Python 3.12, no `$HOME` mount, single workspace
  mount at `~/aipc-workspace/` → `/workspace`).
- [ ] 3.2 `agent-code-shell` wrapper: every call shells through
  `distrobox enter agent-runtime -- <cmd>`; refuse to run if not
  inside the distrobox sandbox context.
- [ ] 3.3 Open Interpreter installed inside the `agent-runtime`
  container at first-assemble; verify with `distrobox enter
  agent-runtime -- interpreter --version`.

## 4. Tools

- [ ] 4.1 `agent-tools-files`: implement read / write / list /
  delete tools; every path passes through the allowlist check
  before any FS syscall; `delete` outside workspace consults the
  permission gate.
- [ ] 4.2 `agent-tools-calendar` Google backend: OAuth flow CLI
  `aipc agent oauth google`; token stored under
  `/var/lib/aipc-agent/oauth/google.json` (0600 user-owned, not
  baked).
- [ ] 4.3 `agent-tools-calendar` Proton backend: documentation +
  Proton Bridge install hint; uses IMAP via the bridge + CalDAV
  endpoint.
- [ ] 4.4 `agent-tools-calendar` Fastmail backend: IMAP + CalDAV
  using a Fastmail app password (user provides at firstboot, not
  baked).
- [ ] 4.5 `agent-tools-search` SearXNG: quadlet + settings; tool
  wrapper queries `127.0.0.1:<searxng-port>` and parses JSON.
- [ ] 4.6 `agent-tools-search` Tavily: opt-in path — runtime reads
  `TAVILY_API_KEY` from the decrypted env file written by the
  `cloud-llm-fallback` runtime oneshot (`aipc-decrypt-cloud-keys.service`);
  appends the key to `secrets/cloud-llm.yaml` schema.
- [ ] 4.7 `agent-screen-control` xdotool/ydotool wrapper: every
  action consults `aipc-agent-gate` for an active screen grant;
  always-on mode consults the blacklist before VLM input and
  before input delivery.
- [ ] 4.8 `agent-screen-control` Qwen2-VL bridge: screenshot via
  Wayland-native tool → base64 → LiteLLM `vlm-qwen2vl` chat
  completion → parsed layout.
- [ ] 4.9 `agent-browser` Playwright MCP: separate browser profile
  for `agent` vs `dev` consumers (profile path declared in the
  registry entry).

## 5. Permission Gate

- [ ] 5.1 `aipc-agent-gate.service` (systemd unit shipped by
  `agent-orchestrator` or its own helper file under
  `agent-screen-control`/`agent-orchestrator`): in-memory grant
  store with sqlite persistence; UNIX-socket RPC at
  `/run/aipc-agent-gate.sock`.
- [ ] 5.2 CLI `aipc agent gate {grant,revoke,status}`: implements
  `--scope session <duration>` and `--scope task <task-id>`,
  `--actions <comma-list>`.
- [ ] 5.3 CLI `aipc agent screen {--mode session <duration>,--mode always,--revoke}`:
  thin wrapper over the gate that issues `screen-control` grants
  with the right scope and a pointer at the blacklist.
- [ ] 5.4 Post-task auto-revoke hook: supervisor signals task done →
  gate revokes all `--scope task <id>` grants for that id.
- [ ] 5.5 Audit log: every grant, every authorisation check, every
  deny appended to `/var/log/aipc-agent-gate.jsonl` (one JSON
  object per line).

## 6. MCP Registry

- [ ] 6.1 Document JSON schema in
  `modules/agent-mcp-gateway/README.md` (fields: `name`, `command`,
  `args`, `transport`, `enabled`, `consumers`, optional
  `profile_path` for Playwright, optional `env` map for tokens).
- [ ] 6.2 Seed `/etc/aipc/mcp/servers.json` with an empty
  `{"version": 1, "servers": []}` document.
- [ ] 6.3 `agent-browser` post-install.sh appends the playwright
  entry to the registry (idempotent: replace-if-exists semantics).
- [ ] 6.4 Confirm Phase 6 `dev-ai-mcp-dev-servers` writes its three
  entries (filesystem, github, playwright) into the same file —
  resolves `phase-6-dev` Open Question Q1.

## 7. Voice Integration

- [ ] 7.1 FastAPI app: `POST /chat` route accepting `{text,
  session_id?}` JSON; binds to `127.0.0.1:4100` (port declared in
  `agent-orchestrator/env/endpoint`).
- [ ] 7.2 Response shape: `{text, task_id}`; errors return
  structured `{error: {code, message}}` with non-200 status.
- [ ] 7.3 Document the Pipecat client config example in
  `agent-orchestrator/README.md` (Phase 3 will consume; this is
  reference, not an implementation here).
- [ ] 7.4 Timeout behavior: default per-request timeout 120 s; long
  tasks return `task_id` immediately and the user polls (or, when
  Phase 7 lands the background daemon, gets notified).

## 8. Doctor Checks

- [ ] 8.1 `aipc doctor`: add `agent-runtime` section running each
  module's `verify.sh`.
- [ ] 8.2 LangGraph import smoke: `python -c "import langgraph"`
  inside `agent-orchestrator`'s runtime environment exits 0.
- [ ] 8.3 Distrobox sandbox check: assert
  `/etc/aipc/distrobox/templates/agent-runtime.yaml` exists and
  parses; assert `agent-runtime` container assembleable (dry-run).
- [ ] 8.4 SearXNG quadlet check: assert
  `aipc-searxng.service` active and responds on its loopback port.
- [ ] 8.5 MCP registry parse check: `jq` parse + schema validation
  against the README-declared schema.
- [ ] 8.6 Permission-gate check: assert `aipc-agent-gate.service`
  active and `/run/aipc-agent-gate.sock` accepts a `status` RPC.
- [ ] 8.7 No-baked-secrets regression: `grep -rE
  '(sk-ant-|sk-proj-|tvly-|client_secret)' modules/agent-*/` must
  exit non-zero.

## 9. Documentation

- [ ] 9.1 Per-module README for each of the 8 modules: purpose,
  packages, files, dependencies, verify behaviour, firstboot user
  actions (OAuth, app password, key provisioning) where applicable.
- [ ] 9.2 `docs/agent-permissions.md`: user docs for the gate CLI —
  session vs task grants, the action class list, what each class
  authorises, default timeout, audit log location.
- [ ] 9.3 `docs/agent-screen-control.md`: when to pick session vs
  always-on, how to edit the blacklist, what the VLM does and does
  not see.
- [ ] 9.4 Update `docs/firstboot-checklist.md` (created by Phase 6)
  to add: `aipc agent oauth google`, Proton Bridge setup, Fastmail
  app password, optional `TAVILY_API_KEY` provisioning.
- [ ] 9.5 Confirm `docs/architecture.md §7` Phase 4 row matches the
  8-module list shipped here (no count change to the §7 header
  total).

## 10. Local Build Verification

- [ ] 10.1 Run `tools/aipc render bootc`; confirm Containerfile
  includes all 8 agent-runtime modules.
- [ ] 10.2 Run `tools/aipc render ansible --check`; confirm it
  lints clean.
- [ ] 10.3 Run each module's `verify.sh` in a privileged container
  against the built image; all non-optional modules exit 0.

## 11. AI PC Hardware Verification

- [ ] 11.1 Deploy `:rolling` tag to the AI PC via `bootc switch`.
- [ ] 11.2 Run `aipc doctor` on the AI PC; confirm agent-runtime
  section all OK (or INFO for unfinished user logins like OAuth).
- [ ] 11.3 Smoke-test: post `{"text":"summarise this file"}` to
  `/chat`; confirm a Researcher run happens and LiteLLM access log
  shows traffic against `coder-fast`.
- [ ] 11.4 Smoke-test code execution: ask the Coder sub-agent to
  write a file under `~/aipc-workspace/`; confirm the file lands
  inside the workspace and outside it is refused.
- [ ] 11.5 Smoke-test screen control: grant `aipc agent screen
  --mode session 1m`, ask the agent to focus a window, confirm the
  grant expires and subsequent calls fail.
- [ ] 11.6 Smoke-test always-on blacklist: open 1Password, enable
  always-on, ask the agent for a screenshot, confirm the
  1Password region is excluded.
- [ ] 11.7 Smoke-test MCP registry sharing: confirm Phase 6's
  Cline (or Goose) sees the same Playwright MCP entry the Browser
  sub-agent uses.

## 12. Archive Change

- [ ] 12.1 Run `npx -y @fission-ai/openspec validate phase-4-agent
  --strict` — must print `Change 'phase-4-agent' is valid`.
- [ ] 12.2 Run `npx -y @fission-ai/openspec archive phase-4-agent` to
  merge the spec into `openspec/specs/agent-runtime/spec.md` and
  close the change.
