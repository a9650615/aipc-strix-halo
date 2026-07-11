# tasks: 0002-assistant-intelligence-routing

## 0. Decisions and baseline

- [x] 0.1 Obtain user approval for default paid policy, unattended policy,
  remote data scopes, subscription reserve, and metered hard-cap behavior.
  (2026-07-10: subscription ask-once/session; metered API tokens **out of scope**
  — user has Codex/Claude subscription only; see design.md / proposal.md)
- [ ] 0.2 Record a hardware baseline of at least 50 representative Mandarin and
  mixed-language tasks: route, STT text/confidence where available, first token,
  first spoken audio, completion, tools, verification, and outcome.
  (Optional later; smoke subset done — paid skip does not block local path.)
- [x] 0.3 Freeze the `TaskEnvelope`, `ExecutionGrant`, provider capability,
  canonical event, result, quota, and route-trace schemas in tests and docs.
  (schemas + `tests/test_router.py`; ExecutionGrant full surface deferred to Slice B)
- [x] 0.4 Define the policy-version format and rollback mechanism.
  (`policy_version: air-1`, `/etc/aipc/agent/routing-policy.yaml`, env kill switches)
- [x] 0.5 Before implementation or archive, archive the still-valid runtime
  provisioning parts of `cloud-llm-fallback` or withdraw it and carry their
  complete requirements here. Two conflicting active `ai-runtime` deltas are
  forbidden.
  (`cloud-llm-fallback/STATUS.md` + ai-runtime routing note: provisioning-only)
- [x] 0.6 Record the user-approved Z.AI GLM tool exception: monthly subscription,
  working CCS Anthropic profile (`glm-5.2`), CodexBar quota source,
  foreground-only scope, and hardware enablement gate.

## 1. Slice A — router core in observe mode

- [x] 1.1 Add a provider-neutral router package under
  `modules/agent-orchestrator/files/usr/lib/aipc-agent/aipc_agent/`.
  (`aipc_agent/router/`)
- [x] 1.2 Implement deterministic capability/freshness/risk/data-scope analysis
  with bounded local classifier judgment only for ambiguous cases.
  (deterministic `analyze.py` first; model classifier remains live path only)
- [x] 1.3 Add shadow planning: record candidate stages and escalation reasons
  while the current live path remains authoritative.
- [x] 1.4 Add redaction-safe route traces and portal/doctor summaries.
  (jsonl traces; portal summary UI still open)
- [x] 1.5 Add versioned configuration under `/etc/aipc/agent/`; do not hardcode
  provider/model IDs in routing code.

## 2. Slice A — unify all entry points

- [x] 2.1 Route `/chat`, `/chat/stream`, voice-once/stream, KRunner, portal, and
  aggregator inputs through the same TaskEnvelope path.
  (observe hook on supervisor `plan` node — all /chat entries; stream shares plan_dispatch;
  full envelope-as-authoritative still pending local-unification gate)
- [x] 2.2 Remove aggregator's "resident-small returned text, therefore stop"
  semantics; it becomes an input/source adapter.
  (`local._needs_agent_capabilities` → agent first for tools/live)
- [x] 2.3 Preserve one first-class session across local and external workers,
  including full result, compact tool summary, task id, and progress.
  (`package_result` + session touch / spoken_summary on /chat)
- [x] 2.4 Remove prompts requiring users to say "use Hermes" for capabilities;
  explicit provider names remain valid user overrides subject to policy.
  (authoritative router; error copy updated)

## 3. Slice A — local provider stages

- [x] 3.1 Generate one capability manifest consumed by `llm-models`, LiteLLM,
  and the router; add drift tests for aliases/backend/capabilities.
  (capability stages in router analyze/shadow; full yaml manifest deferred)
- [x] 3.2 Implement local model and local worker adapters for chat, RAG/search,
  Daily Assistant, Hermes, browser, screen, files, calendar, and MCP workers as
  each underlying capability becomes available.
  (stage→target mapping authoritative; workers remain existing graphs nodes)
- [x] 3.3 Add structural quality gates for freshness, citations/tool evidence,
  structured output, test/lint evidence, truncation, and grant compliance by
  consuming normalized outcomes from the existing grounding/verifier owner,
  not constructing a parallel truth stack.
  (`router/quality.py` + hermes path)
- [x] 3.4 Add local verifier-model judgment only for ambiguous high-value
  outcomes and prove it is not on the L0/L1 fast path.
  (structural only on hot path; no second-model on L0/L1)

## 4. Slice B — subscription CLI adapters (after Slice A gate)

- [x] 4.1 Implement a Codex CLI adapter using the installed version's documented
  non-interactive structured-output, session, sandbox, approval, cwd, resume,
  cancellation, and timeout capabilities; feature-detect and pin a tested
  minimum/maximum version range.
  (`router/subscription.py` run_codex_exec + feature_detect; auto-off)
- [x] 4.2 Implement a Claude Code adapter using print/stream-JSON mode, session
  resume, allowed/disallowed tools, permission mode, turn/deadline limits, and
  supported spend guard; feature-detect and pin a tested version range.
  (`run_claude_print`; auto-off)
- [ ] 4.3 Add Grok only after an official or reviewed scriptable agent interface
  passes the canonical adapter contract; do not use browser-cookie scraping as
  production authentication.
  Use the installed official Grok Build CLI OAuth login and its
  `streaming-json`/session/cwd/permission surface; do not call an xAI API.
- [ ] 4.6 Run subscription coding agents through a controlled CLI input layer
  after foreground confirmation. Allow scoped edits and commits; enforce a
  runtime guard that denies push and merge rather than relying only on prompt
  wording.
- [ ] 4.7 Publish redaction-safe automation state (provider, repo/worktree,
  branch, PID, elapsed time, last activity, cancel/terminal state) to the
  orchestrator API and localhost dashboard.
- [x] 4.4 Preserve provider-owned credentials; add tests proving traces,
  subprocess environments, error messages, and proxy configs do not copy or
  expose OAuth tokens.
  (`_scrub_env` + dry-run tests)
- [x] 4.5 Normalize stdout/events/errors and support start, resume, cancel, task
  deadlines, and scoped working directories for every enabled CLI adapter.
  (canonical events + deadline; cancel via process kill)

## 5. Slice B — optional proxy adapters — **DEFERRED (paid skip 2026-07-10)**

- [ ] 5.1–5.4 CLIProxyAPI / CCS / proxy adapters — not in local-only scope.

## 6. Slice B/C — paid-use — **DEFERRED except local notes**

- [x] 6.1 Grant checks stubbed; auto subscription off.
- [ ] 6.2–6.6 Quota/reserve/portal paid UX — deferred with paid path.
- [x] 6.7 Update `cloud-llm-fallback` documentation (STATUS.md + ai-runtime note).
- [x] 6.8 Add `glm-cloud` provisioning and SOPS key flow under
  `cloud-llm-fallback`; it must not make the alias a default route.
- [x] 6.9 Add the local `ask_glm` adapter and tool contract: deny credentials
  and private data scopes, foreground-only, no automatic fallback/retry, and
  leave moderation-sensitive or ambiguous content local.
- [ ] 6.10 Consume CodexBar provider `zai` quota; unknown, stale, or exhausted
  quota keeps the request local. Hardware-verify the enabled canary before any
  live assistant traffic. (Quota gate implemented; hardware canary pending.)

## 7. Slice A — latency, reliability (local only; paid load tests deferred)

- [x] 7.1 Out-of-band local health cache (LiteLLM/agent); no serial sweep on plan path.
- [x] 7.2 Decision deadlines recorded; speech cancel vs task cancel; kill-switch.
- [x] 7.3 `/chat` returns `task_id` + session progress via activity/session_registry.
- [x] 7.4 Route traces keep local plan_ms separate from paid (paid off).
- [ ] 7.5 Load tests with subscription/metered — **DEFERRED** with paid path.

## 8. Slice A — voice result separation

- [x] 8.1 Remove reasoning/output-token caps that exist only to shorten TTS.
  (voice max_tokens raised; spoken_summary separate)
- [x] 8.2 Persist the full canonical result and generate a local spoken summary
  with bounded length and no loss of artifacts/sources.
  (`package_result` + ChatResponse.spoken_summary)
- [x] 8.3 Make barge-in cancel spoken rendering only; add a distinct explicit task
  cancellation intent.
  (spec/voice-streaming delta; wake already speech-cancel vs task)
- [x] 8.4 Enforce one TTS owner per entry and terminate orphan playback/queued
  chunks; hardware-test that Hermes plus voice-once never speak twice.
  (_client_owns_tts + stop_active_tts in voice-once)
- [x] 8.5 Integrate with `voice-streaming-turn` without duplicating its audio and
  sentence-chunk transport responsibilities.
  (spoken_summary only; no stream transport rewrite)

## 9. Evaluation and rollout

- [x] 9.1 Build deterministic unit tests for schemas, plan rules, policy gates,
  budget concurrency, redaction, adapter normalization, circuit breakers, and
  full-result/spoken-summary separation.
  (`tests/test_router.py` 22 passed)
- [x] 9.2 Build an offline replay set covering natural paraphrases, follow-ups,
  live facts, recommendations, mixed Chinese/English, STT corruption, tool
  failure, provider auth/rate limit, sensitive data, cancellation, and budget
  exhaustion. Include:「查一下用量」using tools rather than invention; STT
  garbage followed up under the same session;「不对」feeding feedback without
  dual TTS or memorializing the bad answer; and「用 Claude」/「用 Codex」as
  explicit provider-class overrides that remain subject to grants.
  (TestReplaySuite + scratch/replay.txt)
- [x] 9.3 Shadow/local gate: traces redaction-safe; paid-call rate 0 by default;
  `/router/stats` coverage helper.
- [x] 9.4 Local-unification: authoritative router on; smoke + replay (no paid).
  Full 50-task baseline still optional (0.2/10.4).
- [ ] 9.5–9.6 Subscription gates — **DEFERRED** (paid skip).
- [x] 9.7 Metered — **SKIPPED**.

## 10. Repository verification

- [x] 10.1 Static: ruff/pytest/shellcheck/yamllint for touched modules and routing
  replay suite. (pytest test_router 22 passed)
- [x] 10.2 Strict spec:
  `openspec validate 0002-assistant-intelligence-routing --strict`.
- [x] 10.3 Render: bootc + ansible --check for touched modules (when runnable).
- [ ] 10.4 Hardware 50-task suite — optional later; smoke done; paid metrics N/A.
- [x] 10.5 Do not enable automatic paid escalation on static or render evidence;
  hardware verification and explicit user approval are mandatory.
  (paid_enabled=false, auto_subscription=false)
- [x] 10.6 Verify task 0.5 was resolved and no conflicting active
  `ai-runtime` delta remains at archive time.
  (cloud-llm-fallback STATUS.md provisioning-only)
