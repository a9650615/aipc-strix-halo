# design: 0002-assistant-intelligence-routing

## Context

Routing is currently split between aggregator mode selection, a front-door
classifier, the LangGraph supervisor, and worker-specific fallbacks. This
change assigns exactly one component authority to produce a RouteDecision;
existing runtimes remain responsible for executing that decision.

## Current Implementation Map

| Current live/repo path | Target | Treatment |
|---|---|---|
| `graphs.plan_dispatch`, classifier, keyword fallback | one versioned RouteDecision | shadow, compare, then replace; delete duplicate terminal routing |
| oneshot Hermes and Daily system-message path | local worker adapter stage | keep execution and wrap as adapters |
| aggregator stops when `resident-small` returns text | input/source adapter | remove terminal policy |
| `grounding.py`, skill-learn, feedback「不对」 | verification and learning inputs | keep/evolve grounding as verifier adapter; no parallel truth stack |
| agent `_speak_best_effort` plus voice-once/KRunner TTS | exactly one TTS owner | trace ownership, then delete duplicate speech |
| fixed `session_id=voice-assistant`, `end_session`, barge-in | first-class session plus separate render/task cancel | keep session adapter; modify cancel semantics in `voice-streaming` delta |
| `cloud-llm-fallback` manual-only/no-budget | policy-approved escalation | resolve archive order before implementation |

## MVP Slices

| Slice | Delivers | Enablement |
|---|---|---|
| A | TaskEnvelope, shadow planner, unified entries, local ladder, quality gates, spoken summary, traces | main delivery; paid providers disabled |
| B | Codex/Claude **subscription CLI** adapters, one-shot ask grants, canary | only after Slice A local gate |
| C | Z.AI GLM `ask_glm` tool canary | SOPS key + explicit spending cap + hardware evidence |
| D | automatic **subscription** escalation | hardware evidence + separate user approval |
| ~~D-metered~~ | generic metered API escalation / hard-cap ledger | deferred; the GLM canary is the sole exception |

## Policy defaults (user-approved 2026-07-10; refined same day)

Slice A keeps paid providers off. When Slice B/C enable subscription:

1. **Subscription (Codex CLI / Claude Code):** interactive → **ask once**
   (session-scoped grant is enough; do not re-prompt every turn).
   Unattended/background → `deny` until an explicit time-bounded grant.
2. **Z.AI GLM API:** one metered exception is permitted as `ask_glm`, a tool
   available to the local main model rather than a default or fallback route.
   It is foreground-only, requires a configured spending cap, and remains off
   until hardware verification. No other metered LiteLLM cloud route is
   enabled for assistant traffic.
3. **Remote data:** default scopes = `prompt` only; coding may add an
   explicitly scoped workspace; personal docs/email/calendar/screen/mem0
   default deny; secrets/credential stores non-exportable always.

## Goals

- Make ordinary language sufficient: the assistant chooses capabilities; the
  user does not need to name Hermes, Codex, Claude Code, or a model.
- Preserve a low-latency local conversational path while allowing long-running
  agents to continue asynchronously.
- Spend subscription quota or metered API money only after a recorded local
  insufficiency decision and policy approval.
- Keep provider-specific authentication, event formats, and session state
  behind adapters.
- Make every escalation explainable and replayable.

## Non-Goals

- Owning worker execution, provider endpoint resolution, session/memory state,
  voice streaming transport, or learning-state mutation.
- Replacing LiteLLM for direct model calls or replacing `agent-gate` for tool
  permissions.
- Treating consumer subscriptions as general API entitlements.

## Decisions

## Architecture

```text
voice / text / portal / KRunner / aggregator
                    |
                    v
             Assistant Router
       normalize + session + data scope
                    |
       +------------+-------------+
       |                          |
 fast local response       capability plan
 (chat/control)       (grounding/tools/reasoning)
       |                          |
       |                 Local workers/models
       |                          |
       |             sufficient? / deadline safe?
       |                    | yes       | no
       |                    v           v
       |                 result     Policy Gate
       |                              /      \
       |                    subscription     metered API
       |                       agent             agent/model
       |                         \                /
       +--------------------------+--------------+
                                  v
                        canonical task result
                         /                  \
                  full text/events       spoken summary
```

The router is part of `agent-orchestrator`. `assistant-aggregator` becomes an
input adapter and optional online source adapter; it no longer owns an
independent "local success means stop" policy.

## D1 — Route by required capability, not topic keyword

**Chosen:** one structured capability decision before worker execution.

**Alternatives considered:** keep keyword routing; allow aggregator and
supervisor to classify independently. Both were rejected because they preserve
misroutes and make traces non-reproducible.

Each request is normalized into a `TaskEnvelope`:

```json
{
  "request_id": "uuid",
  "session_id": "voice-...",
  "source": "voice|text|portal|krunner|api",
  "text": "user request",
  "deadline_ms": 2500,
  "interaction": "foreground|background",
  "required": ["chat"],
  "freshness": "none|recent|live",
  "risk": "read|write|external_side_effect",
  "data_scopes": ["prompt"],
  "paid_policy": "deny|ask|allow_subscription|allow_metered",
  "quality": "fast|balanced|best"
}
```

Deterministic analysis identifies requirements with high objective value:
live/current facts require grounding; desktop state requires screen access;
file changes require a scoped write-capable worker; a greeting requires none.
A deterministic rule or classifier may label capability, freshness, risk, data
scope, quality, and deadline only. Topic or keyword alone MUST NOT alter
capability availability, withhold tools, or force generic chat. Any refusal or
down-rank MUST cite a typed policy dimension and reason code; permission,
privacy, legal, provider, and risk policies remain authoritative.
A small local classifier may resolve ambiguous task shape, but its output is a
hint with confidence, not a terminal worker choice.

The planner emits required capabilities plus confidence and missing evidence.
If confidence is low, the router chooses a harmless local attempt or asks one
clarifying question; it must not silently collapse to generic chat.

## D2 — Local-first is a staged execution policy

**Chosen:** skip provably incapable stages, otherwise move through bounded local
stages before policy-approved remote stages.

**Alternatives considered:** local-only forever; race local and paid providers;
fall back only on HTTP errors. These respectively cap quality, waste quota and
leak data, or fail to detect semantically insufficient answers.

The default ladder is:

1. deterministic local intent for control/time/status;
2. local conversational model for grounded-free chat;
3. local model plus local tools/RAG for freshness or personal context;
4. stronger local reasoning/agent worker;
5. subscription agent adapter if authorized and suitable;
6. metered API adapter if authorized and the previous stages are insufficient.

The router may skip a stage when capability metadata proves it cannot satisfy
the task. It must not spend the entire user deadline trying every local model.

Local insufficiency is one of:

- required capability absent or unhealthy;
- context does not fit after safe summarization/retrieval;
- local quality gate fails (invalid schema, ungrounded claim, failing tests,
  missing citations, or verifier rejection);
- predicted completion misses the task deadline;
- user explicitly requests a provider or `quality=best` and policy permits it.

An endpoint error alone is not evidence that a paid provider is appropriate;
privacy and risk gates still apply.

## D3 — Fast path and latency budgets

**Chosen:** class-specific SLOs, cached provider state, deadline propagation,
and asynchronous long jobs.

**Alternatives considered:** one global timeout or synchronous provider probes.
Both turn backend ceilings into user-visible stalls.

Latency is measured at the router boundary and split by request class.

| Class | Examples | Target on hardware | Behavior |
|---|---|---:|---|
| L0 deterministic | mute, time, portal | p95 decision <= 50 ms | no LLM |
| L1 local chat | greeting, explanation | p95 route <= 120 ms; first text token <= 900 ms warm | no remote probe |
| L2 local grounded | search, calendar, files | acknowledgement <= 700 ms; first useful result <= 2.5 s where tool permits | tool runs async if longer |
| L3 agent task | coding, browser, multi-step | acknowledgement/task id <= 700 ms | progress stream; no voice socket held for job duration |
| L4 remote escalation | subscription/API | escalation decision <= 250 ms after local insufficiency | connection/model latency reported separately |

Targets are acceptance gates, not promises for third-party completion time.
They are provisional until task 0.2 records the 50-task hardware baseline. The
baseline may revise them only through an explicit spec update. Before that
baseline, an L1 p95 120 ms or warm first-token 900 ms miss alone MUST NOT fail
Slice A when task success improves and privacy, routing correctness, and voice
availability do not regress. Cold-start latency is reported separately.
Warm providers are probed out of band. Routing must never synchronously health-
check every provider. Provider calls use deadline propagation, cancellation,
bounded concurrency, and per-adapter circuit breakers.

## D4 — Canonical provider adapter

**Chosen:** normalized lifecycle operations and event types with execution
performed by an executor outside the routing-decision component.

**Alternatives considered:** parse each CLI's terminal prose in the router or
force every provider through OpenAI Chat Completions. Both lose agent events,
permission semantics, and reliable error classification.

Every adapter implements these logical operations:

```text
capabilities() -> ProviderCapabilities
health(deadline) -> ProviderHealth
quota(max_age) -> QuotaSnapshot | unknown
start(TaskEnvelope, ExecutionGrant) -> task_id + event stream
resume(task_id, input, ExecutionGrant) -> event stream
cancel(task_id) -> terminal event
```

Canonical events:

```json
{"type":"accepted","task_id":"...","provider":"codex-subscription"}
{"type":"progress","phase":"testing","message":"..."}
{"type":"tool_request","tool":"shell","risk":"write","scope":"repo"}
{"type":"output_delta","text":"..."}
{"type":"usage","quota_kind":"subscription","units":null}
{"type":"result","text":"...","artifacts":[],"verification":[]}
{"type":"error","code":"rate_limited|auth|timeout|policy|provider"}
```

Provider-specific stdout, JSON, SSE, JSON-RPC, or OpenAI-compatible responses
are normalized inside the adapter. The router never parses terminal prose to
decide whether a tool succeeded.

## D5 — Provider classes

**Chosen:** separate local model, local worker, subscription CLI, optional
proxy, and metered API classes behind the same logical adapter contract.

**Alternatives considered:** represent all providers as LiteLLM aliases or make
CLIProxyAPI mandatory. The former hides tool/session/auth semantics; the latter
creates a third-party single point of failure and trust.

### Local model adapter

- Uses LiteLLM aliases only; no direct Ollama/Lemonade/vLLM calls.
- Capability metadata comes from a single generated manifest, not duplicated
  comments and YAML maintained independently.
- Supports chat/reasoning/vision/structured-output flags and measured latency.

### Local worker adapter

- Wraps Daily Assistant, Hermes, browser, screen, file, calendar, search, and
  future MCP workers.
- Preserves the first-class assistant session and returns compact tool-result
  summaries to the shared short-term context.

### Subscription CLI adapter

- Invokes an installed, officially authenticated CLI as the primary integration
  when that CLI documents non-interactive structured output.
- Initial candidates are Codex CLI and Claude Code. Their adapter contract is
  tested against pinned CLI versions and feature-detected at runtime.
- Credentials remain in the provider CLI's user-owned credential store. The
  adapter never copies OAuth tokens into repo files, LiteLLM configuration, or
  another provider's credential store.
- Each invocation receives an explicit working directory, allowed tools,
  filesystem scope, turn limit, deadline, and permission mode.
- Subscription quota is treated as `unknown` when it cannot be obtained from a
  supported local command/API. Unknown quota never means unlimited quota.

### Optional proxy adapter

- CLIProxyAPI, CCS, or another agent proxy may be configured as a localhost
  provider adapter if its version, protocol, auth ownership, and health are
  declared.
- It is never the default trust boundary and never receives raw provider
  credentials from the router.
- It cannot widen tool permissions, data scopes, or paid policy.
- Direct official CLI adapters remain available so proxy failure cannot remove
  all subscription-agent capability.

### Metered API adapter

- Uses LiteLLM cloud aliases and SOPS-provisioned keys.
- Receives a per-call token/cost ceiling when supported and a router-side hard
  budget reservation in all cases.
- Provider/model mapping is configuration and can change without changing the
  routing contract.

Grok is included when either an official scriptable agent interface or a
reviewed proxy adapter satisfies the canonical contract. Browser-cookie
automation is not an acceptable production credential strategy.

## D6 — Paid-use and privacy gate

**Chosen:** task/session/time-bounded grants plus conservative defaults and a
local budget gate for the sole permitted metered tool.

**Alternatives considered:** provider-side limits only or permanent blanket
approval. Neither prevents concurrent overspend or unintended data export.

Paid use requires all of:

1. local insufficiency evidence or explicit provider request;
2. provider health and compatible capabilities;
3. an `ExecutionGrant` covering data scope and tool risk;
4. quota/budget policy approval;
5. a redacted payload preview/hash recorded in the route trace.

Default policy (this machine — subscriptions plus disabled GLM tool):

| Context | Subscription CLI | Metered API |
|---|---|---|
| foreground, prompt only | ask **once per session** | GLM `ask_glm` after explicit cap + hardware gate |
| foreground, explicitly scoped code repo | ask once per session | GLM `ask_glm` after explicit cap + hardware gate |
| personal docs/email/calendar/screen/mem0 | deny unless explicit data-scope grant | deny |
| unattended/background | deny | deny |
| secrets/credential stores | deny | deny |

The GLM tool is deliberately narrower than generic metered routing. It has no
automatic fallback or retry path. The local main model receives a tool contract
that prohibits requests likely to be refused or moderated; this is best-effort,
not a provider-policy bypass. No second moderation classifier is added: the
hard gate is data scope and credentials, while ambiguous content stays local.

Other metered API adapters, token prompts, and reservation ledgers are out of
scope until the user explicitly revises this policy.

Grants may be one-shot, session-bound, or time-bounded. There is no permanent
"allow everything" voice command. The permission gate remains authoritative for
side effects even after remote use is approved.

Metered budgets use reservation/commit/release semantics to avoid concurrent
jobs exceeding a cap. Subscription quotas use observed reset windows where
available, with configurable reserve percentages for interactive use.

## D7 — Quality gate and selective escalation

**Chosen:** structural verification first and a local verifier only for
ambiguous high-value outcomes.

**Alternatives considered:** trust provider identity or judge every response
with a second model. The former is unsafe and the latter doubles latency/load.

The router does not ask a second model to judge every answer. Cheap structural
checks run first:

- requested schema parses;
- cited URL/tool result exists;
- freshness requirement has a source timestamp;
- code task tests/linters produce a result;
- answer is not empty, truncated, or an error template;
- tool request stayed inside grant scope.

Only ambiguous high-value outcomes use a local verifier model. A remote provider
may be selected after a failed local gate, but its result is subject to the same
verifier. Remote does not imply correct.

## D8 — Full result and voice rendering are separate

**Chosen:** store one complete canonical result and derive a local spoken
summary.

**Alternatives considered:** constrain the worker to TTS length or speak the
entire result. These respectively reduce intelligence or destroy voice UX.

The task produces a canonical full result with artifacts, sources, and
verification. Voice receives a short `spoken_summary` generated locally from
that result, normally no more than three sentences. The full result remains in
the session/portal. Voice token limits must not cap the worker's reasoning or
tool output.

Long work immediately returns an acknowledgement and task id. Progress and
completion use the existing activity/session stream. Barge-in cancels only the
spoken rendering unless the user explicitly cancels the task.

Each entry has exactly one TTS owner for a turn. Voice-once/stream owns voice
TTS; KRunner owns TTS when it elects to speak; agent-side best-effort speech is
allowed only when the client declares it will not speak. Barge-in/cancel paths
terminate orphan playback processes and queued chunks. Explicit task cancel is
a different event from render/speech cancel.

## D9 — Observability and learning

**Chosen:** redaction-safe versioned traces; learned priors may tune scores but
cannot override policy, grants, or explicit user choice.

**Alternatives considered:** full-prompt logs or opaque routing. These create a
privacy liability or make regression analysis impossible.

Every route writes a redaction-safe trace:

```json
{
  "request_id":"...",
  "class":"L2",
  "required":["web_search","freshness:live"],
  "attempts":[
    {"provider":"daily-local","outcome":"tool_unhealthy","latency_ms":42},
    {"provider":"codex-subscription","outcome":"ok","latency_ms":1840}
  ],
  "escalation_reason":"local_capability_unhealthy",
  "paid_policy":"task_grant",
  "data_scopes":["prompt"],
  "result":"ok"
}
```

Traces never contain credentials and default to hashes/previews rather than full
remote payloads. The self-improvement system may learn routing priors from
verified outcomes, but it may not widen paid policy, privacy scopes, or tool
permissions.

## D10 — Rollout

**Chosen:** shadow, local unification, explicit subscription canary, automatic
subscription, metered canary, then separately approved metered automation.

**Alternatives considered:** replace the live route at once. Rejected because
static/render checks cannot prove hardware latency, quota, and cancellation.

1. **Observe:** shadow planner records what it would choose; current path runs.
2. **Local unification:** all entrances use the router; remote escalation off.
3. **Subscription canary:** explicit provider requests only, foreground only.
4. **Automatic subscription escalation:** `ask` once/session, hardware/eval gates met.
5. **Metered API canary / automatic metered:** **skipped** on this deployment
   (subscription-only; no API-token path).

Any stage can revert to the preceding routing policy without removing adapters
or session data.

## Risks and Mitigations

- **Router adds latency:** deterministic fast path, cached capabilities, async
  health/quota refresh, and no serial provider probing.
- **Paid surprise:** default deny/ask, local reservation ledger, per-provider
  reserve, and no unattended paid work by default.
- **Subscription automation breaks:** pinned versions, feature detection,
  structured protocols only, circuit breaker, direct local fallback.
- **Proxy violates provider policy or leaks credentials:** optional-only,
  localhost, no token copying, explicit review and kill switch.
- **Remote data leak:** data-scope grants, denylisted paths, payload redaction,
  and audit hashes.
- **Remote answer still fails:** provider-neutral quality gate and verification.
- **Routing churn:** versioned policy, shadow evaluation, and one owner for route
  selection.

## Relationship to Existing Changes

- `assistant-self-improvement` owns sessions, episodes, learning, and bounded
  routing priors; it does not choose paid providers or widen grants. Learned
  priors may adjust scores only and MUST NOT widen paid/data/tool policy,
  override explicit provider choice, or defeat a grant denial.
- `voice-streaming-turn` owns audio/LLM/TTS streaming transport; this change
  modifies it only for full-result/spoken-summary and single-owner/cancel
  semantics.
- `cloud-llm-fallback` continues to provision API aliases and secrets; its
  manual-only/no-budget decisions are superseded for assistant traffic.
  See that change's `STATUS.md` (task 0.5): provisioning-only, no competing
  assistant routing authority.
- `codexbar-usage-integration` supplies best-effort quota observations; this
  router owns enforcement and treats missing data conservatively.
- `phase-4-agent` owns worker/tool implementations; this change owns choosing
  and composing them.

## External Interface Evidence

- Codex CLI documents non-interactive `codex exec`, structured JSON output,
  resumable sessions, and explicit sandbox/approval controls; the adapter must
  feature-detect the installed version rather than assume flags forever.
- Claude Code documents print mode, JSON/stream-JSON output, session resume,
  tool allow/deny lists, permission modes, turn limits, and an API-spend cap.
- CLIProxyAPI advertises OpenAI/Gemini/Claude/Codex/Grok-compatible local
  interfaces and OAuth support. It remains third-party and optional under this
  design.

The specification deliberately does not promise that a consumer subscription
is a general-purpose API entitlement. Each adapter must use an officially
supported CLI automation surface or be explicitly marked experimental.

Current interface references reviewed for this proposal:

- OpenAI Codex CLI reference: https://developers.openai.com/codex/cli/reference
- OpenAI Codex authentication: https://developers.openai.com/codex/auth
- Anthropic Claude Code CLI reference:
  https://code.claude.com/docs/en/cli-usage
- CLIProxyAPI upstream repository:
  https://github.com/router-for-me/CLIProxyAPI
