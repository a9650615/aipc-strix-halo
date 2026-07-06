## 1. Module Scaffolding (8 modules)

- [x] 1.1 `agent-orchestrator`: real, not just scaffolded —
  `aipc_agent/server.py` (FastAPI `/chat`) + `graphs.py` (supervisor)
  exist and are hardware-verified end-to-end (2026-07-05, see
  `docs/agent-log.md`: real `/chat` round trip through LiteLLM to
  ornith-35b, SELinux `name_connect` fix applied). Daily Assistant
  sub-agent (2.6) and memory/file wiring (8.2) have since landed too —
  see Group 2/4/8 below.
- [~] 1.2 `agent-code-shell`: real safety wrapper implemented 2026-07-06
  (`docs/agent-log.md` phase4-catchup-code-shell) — every call routes
  through `distrobox enter agent-runtime --`, refuses closed if
  already inside a container or if `distrobox` is missing. Real finding:
  this distrobox version (1.8.2.5) has no `--no-home`/`--unshare-home`
  flag, so the host home directory remains reachable inside the sandbox
  at its original path despite the `home=` override — a platform
  limitation, documented plainly rather than silently claimed compliant.
  Static+self-test+render-verified only; module stays `.disabled`
  (no physical distrobox assemble/Open Interpreter install exercised).
- [~] 1.3 `agent-browser`: real Playwright MCP install landed
  2026-07-06 (`docs/agent-log.md` phase4-catchup-browser) — idempotent
  jq-merge registry entry, distinct `profile_path` from
  `dev-ai-mcp-dev-servers`'s own entry, verify.sh checks binary
  presence. `npm install -g @playwright/mcp` was actually exercised
  (in a dev-host distrobox, not the physical AI PC) and confirmed the
  real binary lands — stronger than static, still short of CLAUDE.md
  §9 hardware-verified. Module stays `.disabled`.
- [~] 1.4 `agent-screen-control`: real ydotool input wrapper +
  spectacle/LiteLLM VLM bridge landed 2026-07-06 (`docs/agent-log.md`
  agent-screen-control-2026-07-06, tasks 4.7/4.8), gated through
  `aipc-agent-gate`'s real check RPC (hardware-verified) plus a
  window-class blacklist that fails closed. **Still open**: `kdotool`
  (window-class detection) is static-only on this dev host, so the
  blacklist can't be exercised against a real window yet, and actual
  input injection was deliberately not tested this pass (safety
  constraint — see agent-log). Module stays `.disabled` pending that.
- [~] 1.5 `agent-tools-files`: real read/write/list/delete
  implementation landed 2026-07-06 (task 4.1, `docs/agent-log.md`
  agent-tools-files-2026-07-06) — every path allowlist-checked before
  any FS syscall, delete outside the workspace gated through
  `aipc-agent-gate`. Static+render-verified only, not yet
  hardware-verified.
- [~] 1.6 `agent-tools-calendar`: all three backends implemented
  2026-07-06 (`docs/agent-log.md` phase4-catchup-calendar) — Google
  OAuth flow + token storage (0600, `/var/lib/aipc-agent/oauth/`,
  never baked), Proton/Fastmail via stdlib CalDAV `REPORT` + `imaplib`
  (no new dependency). Real finding: `agent-orchestrator`'s venv lacks
  `--system-site-packages`, so the Google RPMs won't be importable
  from `daily_assistant.py` even once installed — flagged, not fixed
  (out of this task's file scope). No live OAuth/IMAP/CalDAV exercised
  (no credentials in this environment). Module stays `.disabled`.
- [~] 1.7 `agent-tools-search`: SearXNG + Tavily wrapper implemented
  2026-07-06 (`docs/agent-log.md` phase4-catchup-search), same
  stdlib-`urllib`/fail-soft pattern as `agent-orchestrator/aipc_agent/
  memory.py`. Real finding: `secrets-sops`'s decrypt script never
  extracts `tavily_api_key` at all — `search_tavily` will correctly
  self-report `not_configured` forever until that separate gap is
  fixed. No live SearXNG/Tavily exercised. Module stays `.disabled`.
- [x] 1.8 `agent-mcp-gateway`: files-only, no daemon (matches spec).
  verify.sh validates `/etc/aipc/mcp/servers.json` is parseable JSON
  — reasonable minimum given task 1.8's own scope (schema
  documentation + empty seed, not a validator).

**2026-07-06 catch-up dispatch:** after the audit above was written, the
user gave an explicit go-ahead (CLAUDE.md §10) and 5 parallel
isolated-worktree dispatches implemented 1.2/1.3/1.6/1.7 above plus
Groups 3/4/5.3/6 below. Each reserved `tools/aipc_lib/cli.py`,
`agent-orchestrator/aipc_agent/daily_assistant.py`, this file, and
`docs/agent-log.md` for the dispatching session to reconcile centrally
(avoiding a 5-way merge collision on shared files); the five branches
themselves merged into `main` with zero conflicts (disjoint module
directories). See `docs/agent-log.md` `phase4-catchup-*` entries for
full per-module detail. Still unbuilt: Researcher/Coder/Browser
sub-agents (2.3-2.5), the LangGraph checkpointer (2.7), and most of
Groups 8/9/10/11/12 (doctor checks, docs, build/hardware verification,
archive) — none of those were in this dispatch's scope.

**Groups 2/4/5/7/8 status update (2026-07-06, post-audit):** since the
2026-07-06 audit above was written, real work landed on a parallel
branch and has now merged in: Daily Assistant sub-agent (2.6),
agent-tools-files' real implementation (4.1), agent-screen-control's
real ydotool/VLM wrapper (4.7/4.8, still `.disabled`), the permission
gate daemon + CLI (5.1/5.2/5.4/5.5, hardware-verified), and
memory/file-tool wiring into the orchestrator (8.2). See each group
below for the updated checkboxes and `docs/agent-log.md` for the
verification detail.

## 2. Agent Framework (LangGraph)

- [x] 2.1 Pin `langgraph` and `langchain-litellm` versions in
  `agent-orchestrator/packages.txt` (no floating range).
- [x] 2.2 Implement the supervisor graph: accepts `{text, session_id}`
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
- [x] 2.6 Implement Daily Assistant sub-agent graph (default model
  `intent-3b`, tools: calendar, email, files read).
- [ ] 2.7 Configure LangGraph sqlite checkpointer at
  `/var/lib/aipc-agent/checkpoints/`; write `aipc agent resume
  <task-id>` CLI.

## 3. Sandbox + Code Execution

- [~] 3.1 Write `/etc/aipc/distrobox/templates/agent-runtime.yaml`
  (Fedora 41 base, Python 3.12, no `$HOME` mount, single workspace
  mount at `~/aipc-workspace/` → `/workspace`). Implemented; see 1.2's
  `home=` override caveat — real host-home reachability under this
  distrobox version's actual mount behavior, not a code bug.
- [~] 3.2 `agent-code-shell` wrapper: every call shells through
  `distrobox enter agent-runtime -- <cmd>`; refuse to run if not
  inside the distrobox sandbox context. Implemented + self-tested;
  not hardware-verified against a real assembled container.
- [~] 3.3 Open Interpreter installed inside the `agent-runtime`
  container at first-assemble; verify with `distrobox enter
  agent-runtime -- interpreter --version`. Install step wired into
  the template's `init_hooks`; the actual assemble + version check
  was not exercised (no physical AI PC access this dispatch).

## 4. Tools

- [x] 4.1 `agent-tools-files`: implement read / write / list /
  delete tools; every path passes through the allowlist check
  before any FS syscall; `delete` outside workspace consults the
  permission gate.
- [~] 4.2 `agent-tools-calendar` Google backend: OAuth flow CLI
  `aipc agent oauth google`; token stored under
  `/var/lib/aipc-agent/oauth/google.json` (0600 user-owned, not
  baked). Implemented + self-tested (token store/refresh/read paths);
  no live Google OAuth exercised (no client credentials in this
  environment) — see 1.6's venv `--system-site-packages` caveat.
- [~] 4.3 `agent-tools-calendar` Proton backend: documentation +
  Proton Bridge install hint; uses IMAP via the bridge + CalDAV
  endpoint. Implemented via stdlib CalDAV `REPORT`, no new dependency;
  no live Bridge/CalDAV exercised.
- [~] 4.4 `agent-tools-calendar` Fastmail backend: IMAP + CalDAV
  using a Fastmail app password (user provides at firstboot, not
  baked). Implemented via stdlib `imaplib` + CalDAV; app password read
  from a `password_file`, never inline in config; no live IMAP/CalDAV
  exercised.
- [~] 4.5 `agent-tools-search` SearXNG: quadlet + settings; tool
  wrapper queries `127.0.0.1:<searxng-port>` and parses JSON.
  Implemented (`search_searxng`), fail-soft on unreachable endpoint;
  no live SearXNG container in this environment.
- [~] 4.6 `agent-tools-search` Tavily: opt-in path — runtime reads
  `TAVILY_API_KEY` from the decrypted env file written by the
  `cloud-llm-fallback` runtime oneshot (`aipc-decrypt-cloud-keys.service`);
  appends the key to `secrets/cloud-llm.yaml` schema. Implemented
  (`search_tavily`, correctly `not_configured` without a key) — but
  `decrypt-cloud-keys.sh`'s awk filter doesn't actually extract
  `tavily_api_key` yet, so this can't light up end-to-end until that
  separate gap is fixed (flagged, not in this task's file scope).
- [~] 4.7 `agent-screen-control` xdotool/ydotool wrapper: implemented
  2026-07-06, gate check hardware-verified live against the real
  `aipc-agent-gate.service`. `kdotool` window-class detection is
  static-only on this dev host (blacklist fails closed on every
  window until a real image build), and actual input injection was
  deliberately not tested this pass — see `docs/agent-log.md`
  agent-screen-control-2026-07-06. Module stays `.disabled`.
- [~] 4.8 `agent-screen-control` Qwen2-VL bridge: wire format
  (screenshot → base64 → LiteLLM) implemented and hardware-verified
  against real LiteLLM 2026-07-06, but `vlm-qwen2vl` isn't registered
  in this repo's LiteLLM manifest (cut in the 2026-07-04 trim) — got
  the expected HTTP 400, not a working completion. No vision model
  currently exists in LiteLLM at all.
- [~] 4.9 `agent-browser` Playwright MCP: separate browser profile
  for `agent` vs `dev` consumers (profile path declared in the
  registry entry). Implemented — `playwright-agent` entry's
  `profile_path` (`/var/lib/aipc-agent/browser-profile`) is distinct
  from `dev-ai-mcp-dev-servers`'s ephemeral npx profile.

## 5. Permission Gate

- [x] 5.1 `aipc-agent-gate.service`: shipped as its own module
  `modules/agent-gate/`, UNIX-socket RPC at
  `/run/aipc-agent-gate.sock`, in-memory grant store + SQLite
  persistence. Hardware-verified 2026-07-06 (`docs/agent-log.md`
  agent-gate-2026-07-06).
- [x] 5.2 CLI `aipc agent gate {grant,revoke,status}`: implemented
  (`tools/aipc_lib/gate_client.py`), hardware-verified full round
  trip (session + task scope).
- [~] 5.3 CLI `aipc agent screen {--mode session <duration>,--mode always,--revoke}`:
  thin wrapper over the gate that issues `screen-control` grants
  with the right scope and a pointer at the blacklist. Implemented
  (`tools/aipc_lib/screen_client.py` + `cli.py`); tests spin up a real
  (ephemeral) gate daemon, not a mock — but the actual deployed
  `/run/aipc-agent-gate.sock` was not exercised this dispatch.
- [x] 5.4 Post-task auto-revoke hook: bulk task-scope revoke RPC verb
  implemented and verified; the supervisor-side caller that signals
  task-done is not wired up yet (out of scope for this dispatch).
- [x] 5.5 Audit log: append-only JSONL at
  `/var/log/aipc-agent-gate.jsonl`, hardware-verified — every
  grant/check/revoke interleaved correctly, audit-log write failures
  can't take down the RPC path.

## 6. MCP Registry

- [x] 6.1 Document JSON schema in
  `modules/agent-mcp-gateway/README.md` (fields: `name`, `command`,
  `args`, `transport`, `enabled`, `consumers`, optional
  `profile_path` for Playwright, optional `env` map for tokens).
- [x] 6.2 Seed `/etc/aipc/mcp/servers.json` with an empty
  `{"version": 1, "servers": []}` document.
- [x] 6.3 `agent-browser` post-install.sh appends the playwright
  entry to the registry (idempotent: replace-if-exists semantics via
  jq merge, confirmed 2 runs → 1 entry).
- [~] 6.4 Confirm Phase 6 `dev-ai-mcp-dev-servers` writes its three
  entries (filesystem, github, playwright) into the same file —
  resolves `phase-6-dev` Open Question Q1. **Investigated, does NOT
  resolve cleanly**: `dev-ai-mcp-dev-servers` ships a flat
  `{name: {command, args, env}}` object with no `version`/`servers`
  wrapper and no `transport`/`enabled`/`consumers` fields — it doesn't
  conform to the schema documented in 6.1. Both modules are
  `.disabled`; if both were enabled, alphabetical `discover()` order
  means `dev-ai-mcp-dev-servers`'s COPY would silently overwrite
  `agent-mcp-gateway`'s seed with the non-conforming file (no crash,
  schema drift). Flagged in `agent-mcp-gateway/README.md`; left for
  Phase 6 to actually fix per this dispatch's scope boundary.

## 7. Voice Integration

- [x] 7.1 FastAPI app: `POST /chat` route accepting `{text,
  session_id?}` JSON; binds to `127.0.0.1:4100` (port declared in
  `agent-orchestrator/env/endpoint`).
- [x] 7.2 Response shape: `{text, task_id}`; errors return
  structured `{error: {code, message}}` with non-200 status.
- [x] 7.3 Document the Pipecat client config example in
  `agent-orchestrator/README.md` (Phase 3 will consume; this is
  reference, not an implementation here).
- [ ] 7.4 Timeout behavior: default per-request timeout 120 s; long
  tasks return `task_id` immediately and the user polls (or, when
  Phase 7 lands the background daemon, gets notified).

## 8. Doctor Checks

- [ ] 8.1 `aipc doctor`: add `agent-runtime` section running each
  module's `verify.sh`.
- [x] 8.2 LangGraph import smoke: `python -c "import langgraph"`
  inside `agent-orchestrator`'s runtime environment exits 0. Also covers
  `agent-orchestrator` graph self-test in the live venv and fail-closed
  `/etc/passwd` file-read regression.
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
