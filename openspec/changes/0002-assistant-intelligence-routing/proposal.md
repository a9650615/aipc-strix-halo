# proposal: 0002-assistant-intelligence-routing

## Why

The assistant currently exposes several independently routed brains: a fast
chat model, an intent classifier, Daily Assistant, Hermes, online assistants,
and direct cloud aliases. A request that lands on the wrong branch cannot
normally acquire the capabilities of another branch. Users therefore have to
know implementation phrases such as "use Hermes", and the same request can
behave differently depending on whether it entered through voice, KRunner, or
an aggregator.

The machine also has access to three economically and operationally different
classes of intelligence:

1. local models and local tools, whose marginal cost and privacy risk are low;
2. locally authenticated subscription agents such as Codex CLI and Claude
  Code and Grok Build, whose quota and automation contracts differ by product;
3. metered APIs, whose calls create direct cost and send data off-box.

Treating these as interchangeable model aliases would hide cost, privacy,
permissions, and agent state. Treating them as unrelated manual modes would
preserve the current Siri-like fragmentation. The assistant needs one routing
contract that prefers local execution, measures whether it is sufficient, and
escalates only when policy allows and evidence says it is necessary.

## What Changes

- Introduce capability **`assistant-intelligence-routing`**, the single
  front-door decision contract
  for voice, text, portal, KRunner, and aggregator requests.
- Replace keyword-only or endpoint-error fallback with a two-stage decision:
  deterministic request analysis followed by bounded model judgment when the
  decision is ambiguous.
- Keep the interactive fast path local. Grounding, tools, or stronger reasoning
  are attached to the same session instead of requiring a magic phrase.
- Add a provider-neutral agent adapter protocol for:
  - local LiteLLM chat/reasoning models;
  - local tool workers (Daily Assistant, Hermes, browser, screen, files);
  - officially authenticated subscription CLIs (initially Codex CLI and Claude
    Code when installed and authorized);
  - optional proxy adapters such as CLIProxyAPI/CCS;
  - metered provider APIs through LiteLLM.
- Add explicit privacy, permission, quota, latency, quality, and spend gates.
- Separate the complete result from its short spoken rendering so voice length
  limits do not reduce reasoning quality.
- Add routing traces, provider health, quota snapshots, circuit breakers, and a
  replayable evaluation suite with hardware latency gates.
- Supersede `cloud-llm-fallback`'s manual-only routing and no-budget non-goals
  for assistant traffic. Existing cloud aliases remain compatible, but the new
  router owns automatic escalation and spend policy.

Delivery is split deliberately:

- **Slice A — local intelligence foundation:** TaskEnvelope, shadow planner,
  one routing authority, local capability ladder, structural quality gates,
  route traces, and full-result/spoken-summary separation.
- **Slice B — subscription canary:** Codex and Claude Code CLI adapters plus
  session-scoped `ask once` grants. Explicit foreground requests only.
- **Slice C — GLM tool canary:** one SOPS-backed Z.AI API alias, exposed only
  as the main model's `ask_glm` tool. It remains local-first, foreground-only,
  and quota-gated by CodexBar; it is not a generic fallback alias.
- **Slice D — automatic subscription escalation:** after hardware evidence and
  separate user approval. No automatic metered escalation is introduced.

## Capabilities

### New Capabilities

- `assistant-intelligence-routing`: one auditable, transport-neutral,
  policy-constrained RouteDecision from a normalized turn and live capability
  snapshot. It does not execute workers, resolve endpoints, mutate learning
  state, or own session/stream lifecycle.

### Modified Capabilities

- `agent-runtime`: all user-facing entries delegate provider and worker choice
  to the assistant router; workers report structured capability and outcome
  data.
- `ai-runtime`: provider aliases expose capability, locality, billing, health,
  and context metadata; LiteLLM remains the only direct model API gateway.
- `voice-streaming`: receives a spoken summary of the completed or streaming
  task result rather than imposing a small output budget on the reasoning run.

## Non-Goals

- Bypassing provider terms, reverse engineering private endpoints, sharing
  personal subscriptions, or pooling accounts to evade limits.
- Sending secrets, plaintext credential stores, or unrestricted home-directory
  contents to an off-box provider.
- Making a third-party proxy the system of record or a mandatory dependency.
- Automatically granting filesystem, shell, browser, or screen permissions.
- Using paid providers for wake word, VAD, STT, TTS, greetings, local control,
  or other requests the local stack can satisfy within its service level.
- Choosing permanent vendor/model names in code. Providers are adapters and
  policy targets; model IDs remain configuration.

## Impact

- Primary modules: `agent-orchestrator`, `assistant-aggregator`,
  `agent-tools-usage`, `llm-litellm`, `llm-models`, `voice-pipecat`, and the
  existing agent tool modules.
- A new module category is not required. Adapter process/configuration lives in
  `agent-orchestrator`; optional CLIProxyAPI support is an adapter to an
  explicitly configured local endpoint.
- Subscription credentials remain owned by their official CLI/user login.
  API keys remain SOPS-managed by the existing secrets flow.
- User-visible default changes from manual provider selection to automatic
  local-first escalation under a configurable paid-use policy.
- Hardware verification is mandatory before enabling automatic paid escalation
  or replacing the current live route.
- `0002` follows the numeric OpenSpec id convention required by `AGENTS.md`;
  older active siblings retain their historical descriptive-only names.

## Open Questions — resolved 2026-07-10 (refined same day)

1. **Subscription policy:** interactive coding delegation asks once for every
   dispatched task, naming provider and repository. Unattended/background
   dispatch remains `deny` until that task is confirmed.
2. **Z.AI subscription API:** the user approved one exception: a monthly GLM
   subscription may be provisioned as the main model's `ask_glm` tool. It stays
   foreground-only and local-first; CodexBar supplies remaining quota and reset
   time. Unknown or exhausted quota keeps the request local.
3. **Remote data:** default `prompt` only; scoped repo for coding on grant;
   personal docs/email/calendar/screen/mem0 deny unless data-scope grant;
   secrets never exportable.
4. **Coding delegation:** every external CLI dispatch requires a foreground
   confirmation naming provider and repository. The delegated CLI MAY edit and
   commit on its task branch, but SHALL NOT push or merge.
5. **Automation visibility:** the localhost dashboard shows every active
   controlled CLI with provider, repository/worktree, branch, PID, elapsed
   time, last activity, and cancellation state.
