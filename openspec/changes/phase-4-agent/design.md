## Context

Phase 4 is the agent layer. Phases 0–1 give us the OS and the LLM
gateway; Phase 6 gives us the IDEs and the dev MCP servers. Phase 4
ships the long-lived daemons and sub-agents that *use* those models and
those tools to act on the user's machine.

The hard requirements are: every LLM call goes through LiteLLM (CLAUDE.md
§7); no secret is baked into the image (§5); the image must work offline
once weights are present (§6); modules render identically through bootc
and ansible (§4). Within those, the design choice is multi-agent
supervisor + four shipped sub-agents, sandboxed code execution, shared
MCP registry config, and a single permission gate for risky actions.

## Goals / Non-Goals

**Goals:**

- A user can voice or type a goal, the supervisor picks a sub-agent (or
  parallelises across sub-agents), and the agent acts — with explicit
  permission for risky actions and a single audit trail.
- Every sub-agent addresses models by alias through LiteLLM. Model swap
  is a `models.yaml` edit, not a per-sub-agent config edit.
- Code execution is sandboxed by default. A prompt injection cannot
  `rm -rf $HOME`.
- Screen control is opt-in per session and explicitly bounded; the
  user's password manager and banking windows are never visible to the
  VLM in always-on mode.
- One MCP registry file is the single source of truth for which MCP
  servers exist on the box; Phase 6 dev tools and Phase 4 sub-agents
  read the same file.

**Non-Goals:**

- Single-agent ReAct loop with tool soup. Not chosen — see D2.
- Browser-use as the browser backend. Not chosen — see D6. Playwright
  MCP is shipped instead.
- A long-running background task daemon (queue + notification center
  integration). Deferred to Phase 7 ops — see Q3.
- Dynamic sub-agent spawn at runtime (supervisor creates a new role on
  the fly). Deferred to v2 — see Q2.
- Apple iCloud calendar/mail backend. Out of scope — Google + Proton /
  Fastmail cover the 80/20 (see D8).
- A central MCP-gateway daemon (HTTP proxy in front of MCP servers).
  Not shipped today — the registry is a config file (see D9). A daemon
  can be inserted later without changing the registry contract.

## Decisions

**D1 — LangGraph as the agent framework**

*Chosen:* LangGraph is the single framework for every agent loop in
Phase 4: the supervisor, the four sub-agents, and any future sub-agent.
Graph state is checkpointed to a sqlite file under
`/var/lib/aipc-agent/checkpoints/`.

*Alternatives:*
- Pydantic AI: lighter, no graph or built-in state. Good for single-call
  tool use, weak for multi-agent topologies.
- OpenAI Agents SDK: vendor-shaped around OpenAI's tool format and
  Realtime API; mixing local models in is awkward.
- Hand-rolled supervisor + sub-agent loops on top of LiteLLM only:
  works, but reinvents checkpoint/replay and state machine machinery.

*Why chosen:* Graph-based state + native checkpoint/replay matches the
multi-agent topology in D2; the largest Python ecosystem around
agent-frameworks means the existing tutorials and MCP integrations
mostly target it. Single-framework rule (only LangGraph in this phase)
avoids the trap of three half-integrated frameworks.

**D2 — Multi-agent supervisor with four shipped sub-agents**

*Chosen:* One supervisor (`main-70b`) plus four sub-agents:
- **Researcher** — search + browser + RAG. Default model `coder-fast`;
  supervisor may override to `main-70b` for hard questions.
- **Coder** — file + shell + git. Default model `coder-strong`.
- **Browser** — Playwright MCP only. Default model `vlm-qwen2vl`
  (DOM-only navigation falls back to the VLM when the page is opaque).
- **Daily Assistant** — calendar + email + memory. Default model
  `intent-3b`.

The supervisor decomposes a goal, can fan-out to multiple sub-agents in
parallel, and merges results.

*Alternatives:*
- Single agent + tool soup: simpler, no parallelism, no per-tool model
  cost optimisation (Browser would still wake the 70B to read a page).
- Persona-based (one model, swap system prompts): no real isolation —
  the "Coder persona" can still call the email tool if its prompt is
  jailbroken.

*Why chosen:* Parallelism (Researcher and Coder can run concurrently
under the supervisor); per-sub-agent model choice (Browser needs a VLM
not a 70B); hard isolation of dangerous tools (Coder has shell, Daily
Assistant does not). Cost: more graphs to maintain — accepted because
each graph is small and the supervisor pattern is well-trodden.

**D3 — Code execution sandboxed in a distrobox container**

*Chosen:* A new distrobox template `agent-runtime` (parallel to Phase
6's `node` and `python` templates), declared at
`/etc/aipc/distrobox/templates/agent-runtime.yaml`. Open Interpreter is
installed inside it; `agent-code-shell` shells out to
`distrobox enter agent-runtime -- ...`. Host paths are mounted
explicitly per template — the agent does not see `$HOME` by default.

*Alternatives:*
- Podman quadlet (immutable, no install persistence): bad for the
  exploratory workflows Open Interpreter enables (`pip install x` mid-
  session must persist).
- Run on the host: one prompt-injection away from `rm -rf $HOME`.
- Firecracker microVM per agent task: overkill, and GPU sharing on
  Strix Halo would be a nightmare.

*Why chosen:* Distrobox is fedora-toolbox-shaped — the agent can
install libraries, host system files are protected, the user's
`~/.local/share/containers` for their own dev distroboxes is untouched.
Same pattern as Phase 6, low cognitive overhead.

**D4 — Screen control: session-gate default, always-on + blacklist opt-in**

*Chosen:* Two modes, both shipped.
- **session-gate (default)**: user says "next 30 min the agent can
  control the screen" and gets a time-bounded grant. The grant expires
  automatically; no per-action prompt.
- **always-on (opt-in)**: a daemon stays on, but a window-class
  blacklist hides matching windows from the VLM and from input
  delivery. Default blacklist: password managers (1Password, GNOME
  Keyring), banking domains (when run inside Zed/VSCode browser
  preview), SSH terminals. User edits
  `/etc/aipc/agent-gate/screen-blacklist.conf` to extend.

CLI: `aipc agent screen --mode session 30m` /
`aipc agent screen --mode always` / `aipc agent screen --revoke`.

*Alternatives:*
- Per-action prompt (confirm every click): high overhead, broken UX
  for multi-step automation.
- Voice-confirm per high-risk action: requires Phase 3 voice loop,
  couples Phase 4 to Phase 3 timing.

*Why chosen:* Personal machine, user willing to accept some risk in
exchange for usability; both modes shipped so the user picks per
session. Window-class blacklist is the lazy form of "tell the model
which windows it cannot see" and is sufficient until something
specific breaks it.

**D5 — Risky-action permission: session-gate (default 30 min) + per-task-loop**

*Chosen:* Risky actions are: file delete outside the agent workspace,
git push, package install (host or distrobox), email send, cloud API
call (cost). The user grants permission via the same `aipc-agent-gate`
daemon as D4, in one of two scopes:
- **session**: time-bounded ("this 30 min I'm authorising risky
  actions").
- **per-task-loop**: bounded to a single supervisor task ("for the
  'refactor X' task only"); the grant is auto-revoked when the
  supervisor reports the task done.

CLI: `aipc agent gate grant --scope session 30m
--actions=file-delete,git-push,email-send` /
`aipc agent gate grant --scope task <task-id> --actions=...` /
`aipc agent gate revoke` / `aipc agent gate status`.

*Alternatives:*
- Per-action prompt: annoying, gets click-tired and rubber-stamped.
- Trust agent: irresponsible — the model is wrong sometimes and a wrong
  `git push --force` is unrecoverable.

*Why chosen:* Matches the user's mental model — "I'm starting a chunk
of work, agent can do dangerous stuff during it". Time bound and task
bound are both natural framings; both shipped.

**D6 — Browser via Playwright MCP, not browser-use**

*Chosen:* `agent-browser` installs Playwright MCP and registers it with
the shared MCP registry. The Browser sub-agent connects to the same
MCP server every Phase 6 dev tool connects to. When DOM-only navigation
fails (opaque page, canvas app), the Browser sub-agent layers
`vlm-qwen2vl` on top: screenshot → VLM describes layout → DOM action.

*Alternatives:*
- browser-use: LLM drives every page interaction. Expensive in tokens,
  non-deterministic, hard to debug. The 80% case is "click this link" —
  paying a 70B token cost per click is wasteful.
- CDP direct: would need custom tooling around the Chrome DevTools
  Protocol; no MCP interop with Phase 6.

*Why chosen:* Playwright MCP is deterministic, speaks MCP natively, and
ships with the Phase 6 dev tools anyway — one browser backend, shared
across phases. The VLM layer is the escape hatch for visual reasoning
when DOM-only does not suffice.

**D7 — Search: SearXNG self-host default, Tavily opt-in**

*Chosen:* SearXNG runs as a quadlet on `127.0.0.1` (port chosen by the
quadlet, declared in `modules/agent-tools-search/env/endpoint`). Tavily
is optional: if `TAVILY_API_KEY` exists in `secrets/cloud-llm.yaml`
(the same SOPS file used by `cloud-llm-fallback`, decrypted by the
same runtime oneshot), the search tool exposes both `search.searxng`
and `search.tavily`; otherwise only `search.searxng`.

*Alternatives:*
- Brave Search API: paid, no offline mode.
- Tavily-only: paid, no offline mode, single point of failure.
- Skip search entirely: Researcher sub-agent becomes useless.

*Why chosen:* SearXNG is privacy-default and offline-capable (it
proxies to public engines but caches and can be self-shaped). Tavily is
the paid quality upgrade for research-critical work, gated on whether
the user has provided a key — same pattern as the cloud LLM keys.

**D8 — Calendar/Mail backends: Google (OAuth) + Proton/Fastmail (IMAP/CalDAV bridge)**

*Chosen:* `agent-tools-calendar` exposes a backend-agnostic API to
sub-agents (`calendar.list_events`, `email.send`, etc.). Backends:
- Google via OAuth (calendar + Gmail).
- Proton / Fastmail via IMAP + CalDAV (Proton's bridge daemon for IMAP,
  Fastmail's native CalDAV).

Apple iCloud is explicitly out of scope.

*Alternatives:*
- All-providers slot model (every IMAP / every CalDAV / every OAuth
  provider): generic but the 80/20 is Google + one of Proton/Fastmail
  for this user.
- iCloud: user is Mac-native but explicitly does not want lock-in;
  exclusion is the user decision.

*Why chosen:* 80/20 — these two backends cover most users without
fanning out a vendor matrix. Backend-agnostic API means iCloud can be
added later without touching the sub-agents that call the tool.

**D9 — MCP gateway = shared config registry, not a daemon**

*Chosen:* `agent-mcp-gateway` ships exactly one file:
`/etc/aipc/mcp/servers.json` (JSON schema declared in the module
README). Every MCP-aware client reads it directly. MCP servers
themselves run as independent processes per the MCP spec — clients
connect to each via stdio or sse, no proxy in between.

Clients in this image that consume the registry:
- Phase 4 sub-agents: Researcher, Coder, Daily Assistant.
- Phase 6 dev tools: Zed, Continue, Cline, Aider, Goose, OpenCode,
  Claude Code CLI.

*Alternatives:*
- punkpeye/mcp-gateway style HTTP proxy daemon: adds central audit,
  adds a hop, adds a daemon to keep alive. Useful eventually, premature
  today.
- Make Goose the gateway: Goose is a focused agent, wrong layer.
- Per-client config (each tool declares its own MCP server list): the
  fan-out problem Phase 6 already pushes back on (CLAUDE.md §3).

*Why chosen:* Simplest thing that works. The registry contract is just
"this file lists the servers"; a daemon can be inserted between
clients and servers later without changing this contract. Phase 6's
`dev-ai-mcp-dev-servers` writes to this file; Phase 4 sub-agents read
from it.

**D10 — Voice → agent interface: HTTP POST `/chat`**

*Chosen:* `agent-orchestrator` exposes a FastAPI endpoint `POST /chat`
on `127.0.0.1:4100` (port declared in
`modules/agent-orchestrator/env/endpoint`). Body: `{"text": "...",
"session_id": "..."}`. Response: `{"text": "...", "task_id": "..."}`.
Phase 3 Pipecat is the only producer: STT → POST → TTS.

*Alternatives:*
- Agent-as-MCP server: higher latency for the simple "send a message"
  case, awkward streaming.
- WebSocket streaming (mid-task narration: "I'm searching now..."):
  best UX, but more complex client and server. Deferred to v2.

*Why chosen:* Simplest. The voice multimodal first-layer choice
(Qwen2.5-Omni audio-in directly vs separate STT → LLM) is a Phase 3
decision that does NOT change this contract — Pipecat still emits text
either way. Websocket streaming is a strict additive upgrade once the
basic loop is solid.

**D11 — Long-running tasks: inline + LangGraph checkpoint, no background daemon**

*Chosen:* Tasks run foreground; LangGraph checkpoints state to sqlite
under `/var/lib/aipc-agent/checkpoints/`. On crash or reboot, the user
runs `aipc agent resume <task-id>` to continue from the last
checkpoint.

*Alternatives:*
- Inline only, no checkpoint: lose progress on crash.
- Full background daemon (task keeps running while user does other
  things, notification center integration when done): Phase 7 ops, out
  of scope for this change.

*Why chosen:* Covers the 80% case (single-session work) without the
daemon complexity. The Phase 7 ops layer is the right home for the
background daemon — see Q3.

## Risks / Trade-offs

- **Distrobox sandbox is not a security boundary the way a VM is.** A
  determined kernel exploit escapes. **Mitigation**: the default mount
  set is narrow (no `$HOME`, no `/etc`); the workspace is a single
  mounted directory the agent can wreck without harming the host.
- **Playwright MCP browser state**: the same browser is shared between
  the Browser sub-agent and Phase 6 dev tools. **Mitigation**: separate
  browser profiles per consumer (`agent` vs `dev`), declared in the
  Playwright MCP registry entry.
- **Always-on screen-control blacklist may miss a window.** A renamed
  banking website or a custom-titled password manager slips through.
  **Mitigation**: blacklist is config-editable; default mode is
  session-gate, not always-on; always-on is opt-in and the user has
  acknowledged the risk by enabling it.
- **Permission-gate becomes click-tired**: if the user grants
  "session 30 min, all actions" routinely, the gate degrades to a
  rubber stamp. **Mitigation**: `aipc agent gate status` and the
  audit log surface what was authorised; `aipc doctor` can later add
  a warning if the same broad grant is recurring.
- **SearXNG cache hygiene**: SearXNG caches responses to disk; sensitive
  queries persist. **Mitigation**: ship with cache TTL short and cache
  dir under `/var/lib/aipc-agent/searxng-cache/` which `aipc agent
  cache purge` clears.
- **LangGraph version churn**: LangGraph's API has been moving fast.
  **Mitigation**: pin the version in `agent-orchestrator/packages.txt`;
  upgrades go through a spec change.

## Migration Plan

No prior agent runtime exists. Phase 4 is net-new. The only inbound
dependency is Phase 6's `dev-ai-mcp-dev-servers` — that module ships
the MCP server binaries and writes a registration manifest at the path
this change declares (`/etc/aipc/mcp/servers.json`). The Phase 6 spec
already gates its registration step on this Phase 4 spec landing
(`phase-6-dev/design.md` Q1).

## Open Questions

- **Q1 — Voice multimodal first-layer (Phase 3)**: Phase 3 may choose
  Qwen2.5-Omni audio-in directly (no separate STT) or pipeline STT →
  LLM → TTS. The Phase 4 voice contract (HTTP `/chat` with text) is
  unaffected either way — Pipecat still emits text — but flagging
  cross-phase so the choice does not silently change the contract.

- **Q2 — Dynamic sub-agent spawn at runtime**: the supervisor creates a
  new sub-agent role on the fly (e.g., "spawn a Data Analysis sub-agent
  for this task only"). Requires runtime graph mutation in LangGraph
  plus a safety review (what tools does a dynamically-spawned sub-agent
  inherit?). Deferred to v2.

- **Q3 — Background long-running task daemon (Phase 7 ops)**: task
  queue, systemd timer for long jobs, notification center integration
  for "task done, here is the result". Out of scope for Phase 4; the
  inline + checkpoint pattern covers the single-session case.

- **Q4 — Always-on screen-control default window blacklist**: suggested
  set is 1Password, GNOME Keyring, banking domains, SSH terminals.
  Needs hardware verification once the bazzite-dx image is on the AI
  PC to confirm what is actually installed and what window classes
  they expose. The blacklist file ships with the suggested set; the
  user can edit before enabling always-on.
