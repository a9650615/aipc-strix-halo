# assistant-intelligence-routing Specification Delta

## ADDED Requirements

### Requirement: Single assistant routing authority

The system SHALL route every user-facing assistant request from voice, text,
portal, KRunner, and aggregator inputs through one assistant-routing authority.
No input adapter SHALL independently terminate routing merely because a small
local model returned syntactically valid text.

#### Scenario: Equivalent inputs share policy

- **WHEN** equivalent requests arrive through voice and text with the same
  session, grants, and freshness requirements
- **THEN** they SHALL receive the same capability plan and paid-use policy even
  if their presentation differs

#### Scenario: No magic provider phrase required

- **WHEN** a natural-language request objectively requires current web data,
  repository edits, or another registered capability
- **THEN** the router SHALL attach a capable worker without requiring the user
  to name Hermes, Codex, Claude Code, or a model

### Requirement: Capability-aware planning

The router SHALL represent required capabilities, freshness, interaction mode,
risk, data scopes, quality target, and deadline separately from provider/model
selection. Classifier output SHALL be advisory and include confidence or a
documented fallback reason.

Deterministic analysis and classifiers MUST classify typed planning dimensions
only: capability, freshness, risk, data scope, quality, and deadline. Topic or
keyword alone MUST NOT change capability availability, withhold tools, or force
generic chat. Any refusal or down-rank MUST cite a typed policy dimension and
reason code. Learned priors MUST NOT override explicit provider choice,
paid/data/tool policy, or an ExecutionGrant denial.

#### Scenario: Live information requires grounding

- **WHEN** the user requests a price, availability, schedule, recommendation,
  or other information whose correctness depends on current external state
- **THEN** the plan SHALL require an appropriate live grounding capability and
  SHALL NOT satisfy the request with ungrounded model memory

#### Scenario: Ambiguous classification

- **WHEN** the classifier is unavailable, times out, emits invalid output, or
  has confidence below policy threshold
- **THEN** the router SHALL use deterministic evidence, a safe local attempt, or
  one clarification and SHALL record the fallback instead of silently choosing
  generic short chat

### Requirement: Local-first staged execution

The router SHALL prefer deterministic local functions, local models, local
RAG/tools, and stronger local workers before an off-box provider when they can
satisfy the task within the requested quality and deadline.

#### Scenario: Local capability succeeds

- **WHEN** a local stage passes the task quality gate within its deadline
- **THEN** the router SHALL return that result without invoking a subscription
  or metered provider

#### Scenario: Incapable local stage is skipped

- **WHEN** provider metadata proves a local model cannot use required tools or
  accept the required modality/context
- **THEN** the router SHALL skip that stage rather than spend the user deadline
  waiting for a guaranteed failure

#### Scenario: Local insufficiency is recorded

- **WHEN** routing escalates beyond local execution
- **THEN** the trace SHALL contain a machine-readable reason such as missing
  capability, failed quality gate, unhealthy service, context overflow, missed
  deadline prediction, or explicit user provider request

### Requirement: Paid-provider policy gate

The system SHALL NOT invoke a subscription agent or metered API unless local
insufficiency or explicit user choice is established and an execution grant,
data-scope policy, provider health check, and quota/budget policy all permit it.

#### Scenario: Default interactive subscription delegation

- **WHEN** a foreground coding task needs subscription-CLI delegation
- **THEN** the assistant SHALL ask once for that task, naming the provider and
  repository scope, and SHALL require another confirmation for another task

#### Scenario: Default unattended policy

- **WHEN** a background or unattended task reaches a paid escalation point
  without an explicit pre-authorized allowance
- **THEN** it SHALL pause in `waiting_user` rather than spend quota or money

#### Scenario: Sensitive data scope

- **WHEN** a remote attempt would include personal documents, email, calendar,
  screen content, mem0 content, a credential store, or secret material
- **THEN** default policy SHALL deny it unless an explicit compatible data-scope
  grant exists; credential and secret contents SHALL remain non-exportable

#### Scenario: Metered API path disabled by default

- **WHEN** metered API / provider API-token routing is not enabled in policy
  (default on subscription-only deployments)
- **THEN** the router SHALL NOT select metered adapters, SHALL NOT prompt for
  API tokens, and SHALL NOT require a metered budget ledger for assistant traffic

#### Scenario: Metered budget reservation (only if metered re-enabled)

- **WHEN** policy explicitly enables metered routing and concurrent metered jobs
  request budget
- **THEN** the local ledger SHALL atomically reserve estimated spend before
  dispatch and SHALL reject work that could exceed the configured hard cap

### Requirement: Provider-neutral agent adapters

Every provider adapter SHALL expose normalized capabilities, health, quota,
start/resume/cancel, event,
result, usage, and error semantics to the router.

#### Scenario: Structured event normalization

- **WHEN** Codex CLI, Claude Code, or another adapter emits provider-specific
  structured output
- **THEN** the adapter SHALL translate it into canonical accepted, progress,
  tool-request, output-delta, usage, result, or error events

#### Scenario: Unsupported automation surface

- **WHEN** a provider lacks a documented or reviewed non-interactive structured
  interface compatible with the adapter contract
- **THEN** that provider SHALL remain disabled or experimental and SHALL NOT be
  selected automatically

#### Scenario: Credentials remain provider-owned

- **WHEN** a subscription CLI is used
- **THEN** the adapter SHALL use its official user-owned login state and SHALL
  NOT copy OAuth tokens into the repository, LiteLLM, logs, or proxy config

### Requirement: Optional proxy containment

Optional proxies SHALL remain contained adapters: CLIProxyAPI, CCS, and similar
proxies MAY be configured, but SHALL NOT be required for local routing or direct official CLI adapters and
SHALL NOT widen execution grants or data scopes.

#### Scenario: Proxy failure

- **WHEN** an optional proxy is unhealthy, incompatible, or circuit-open
- **THEN** the router SHALL remove it from candidates without disrupting local
  providers or compatible direct CLI adapters

#### Scenario: Proxy credential boundary

- **WHEN** a proxy requires credentials not already owned by that proxy's
  reviewed login flow
- **THEN** the assistant router SHALL refuse to export provider OAuth tokens to
  it automatically

### Requirement: Low-latency critical path

On the target Strix Halo hardware, the router SHALL target the following warm-path
targets: L0 deterministic p95 decision at most 50 ms; L1 local-chat p95 route at
most 120 ms and first text token at most 900 ms; L2/L3 acknowledgement or task id
at most 700 ms. Remote-provider completion time SHALL be measured separately.
These targets MAY be revised by an explicit spec update after the required
50-task hardware baseline. Before that baseline, an L1 target miss alone SHALL
NOT block local unification when task success improves and privacy, routing
correctness, and voice availability do not regress.

#### Scenario: No synchronous provider sweep

- **WHEN** a request is routed
- **THEN** health, capability, and quota snapshots SHALL come from bounded local
  caches refreshed out of band; the critical path SHALL NOT probe every provider
  serially

#### Scenario: Long-running task

- **WHEN** predicted completion exceeds the foreground response deadline
- **THEN** the router SHALL return a task id and acknowledgement, stream progress
  through the session activity channel, and allow cancellation

### Requirement: Quality-gated escalation

The system SHALL evaluate task-specific structural evidence before accepting a
result or escalating, and SHALL apply the same acceptance criteria to local and
remote results.

#### Scenario: Coding task verification

- **WHEN** a coding task requires tests or linting
- **THEN** a result claiming completion SHALL include normalized verification
  evidence or be marked incomplete; provider identity alone SHALL NOT satisfy
  the gate

#### Scenario: Grounded answer verification

- **WHEN** freshness or external grounding is required
- **THEN** the accepted result SHALL include a source/tool timestamp and usable
  source identifier; an uncited model assertion SHALL fail the gate

### Requirement: Full result and spoken summary separation

The assistant SHALL preserve the complete task result, artifacts, sources, and
verification in the session while generating a separate short spoken summary
for voice output.

#### Scenario: Voice request requires deep work

- **WHEN** a voice request requires long reasoning, tools, or substantial text
- **THEN** voice length/token limits SHALL apply only to the spoken summary and
  SHALL NOT cap the worker's reasoning, tool output, or stored full result

#### Scenario: Barge-in during speech

- **WHEN** the user interrupts spoken rendering without explicitly cancelling
  the task
- **THEN** speech SHALL stop while the underlying task and full result remain
  available

#### Scenario: Exactly one speech owner

- **WHEN** a worker returns a result to a client that owns TTS for the turn
- **THEN** the worker SHALL NOT start agent-side TTS and cancellation SHALL stop
  every playback process or queued chunk owned by that turn

### Requirement: Routing observability and circuit breaking

The system SHALL record a redaction-safe route trace containing request class,
required capabilities, attempted providers, timing, outcomes, escalation
reason, paid policy, data scopes, and final result. Each adapter SHALL have a
bounded timeout and circuit breaker.

#### Scenario: Provider repeatedly fails

- **WHEN** an adapter crosses its configured failure threshold
- **THEN** its circuit SHALL open, routing SHALL stop selecting it until the
  recovery window/probe succeeds, and local operation SHALL continue

#### Scenario: Trace redaction

- **WHEN** a route trace is persisted or shown in the portal
- **THEN** it SHALL exclude credentials and secret contents and SHALL default to
  hashes or bounded previews for remote payloads

### Requirement: Controlled rollout and evaluation

Automatic paid escalation SHALL remain disabled until the shadow, local-only,
explicit subscription canary, and hardware evaluation stages pass their gates.

#### Scenario: Routing regression gate

- **WHEN** the representative replay suite shows a statistically meaningful
  regression in task success, privacy violations, paid-call rate, or latency
- **THEN** rollout SHALL stop or revert to the preceding policy version

#### Scenario: Hardware enablement

- **WHEN** only static and render verification have passed
- **THEN** automatic subscription or metered escalation SHALL remain disabled;
  enabling requires hardware-verified latency, tool, permission, cancellation,
  quota, and failure-path tests
