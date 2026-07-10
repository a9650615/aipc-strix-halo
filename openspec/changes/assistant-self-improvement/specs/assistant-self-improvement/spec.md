# assistant-self-improvement

## ADDED Requirements

### Requirement: Session lifecycle

The system SHALL maintain a first-class **session** object with at least:
`id`, `status` (`active` | `working` | `waiting_user` | `done` | `failed`),
`updated_ts`, optional `job_id`, optional `title`, and short-term memory
bound to that id.

#### Scenario: Multi-turn tool continuum

- **WHEN** the user asks to look up AMD stock, receives a result, then asks
  for another day or related follow-up without farewell
- **THEN** the follow-up SHALL use the **same open session** and its
  short-term turns (including prior tool result summary)

#### Scenario: Session stays open after job success

- **WHEN** a background or Hermes job completes successfully
- **THEN** the session status becomes `active` (or `waiting_user` if a
  slot is pending), not `done`, unless `end_session` is true

#### Scenario: Session complete clears STM after consolidate

- **WHEN** the session ends (farewell, explicit done, or configured idle)
- **THEN** the system enqueues consolidation and clears short-term memory
  for that session id

### Requirement: Multi-horizon memory

The assistant SHALL maintain three memory horizons:

1. **Short-term** — recent dialogue turns **for an open session only**
2. **Mid-term** — session episodes and pending multi-turn slots
3. **Long-term** — durable facts stored via mem0 with inference

#### Scenario: Short-term reference

- **WHEN** the user refers to a prior turn in the same open session
  (e.g. “那个”, “刚才说的”, “其他天”, “我叫什么”)
- **THEN** the respond/tool path SHALL use short-term history so the
  reply is grounded in those turns

#### Scenario: Long-term preference survives session end

- **WHEN** the user states a durable preference and the session later ends
- **THEN** after consolidation completes, a later session SHALL be able to
  recall that preference via mem0 search on the chat lane

### Requirement: Activity notify for in-flight sessions

While a session is `working` (or a linked job is running), the system
SHALL publish real-time activity updates to at least:

1. Voice overlay progress detail
2. A portal/desktop activity surface listing open sessions
3. Desktop notifications on meaningful phase changes and on completion
   (phase notifies throttled)

#### Scenario: User sees Hermes progress

- **WHEN** Hermes is running a stock lookup for the open session
- **THEN** overlay (or equivalent) shows a non-empty progress line that
  updates at least on phase boundaries (start / tool / done)

#### Scenario: Portal lists open activity

- **WHEN** at least one session is `working` or `active` with a recent job
- **THEN** the portal Activity view SHALL list it with `last_activity`
  text without requiring a full page reload more stale than a few seconds
  (poll or push)

#### Scenario: Completion notify does not kill session

- **WHEN** a job completes and a desktop notify is shown
- **THEN** the session remains available for follow-up unless
  `end_session` was requested

### Requirement: Continuous internalization

After a successful worker turn that produced a user-visible reply, the system SHALL enqueue continuous internalization:

- Input includes user text and assistant text
- mem0 write uses **infer=true** for fact extraction
- The write MUST be asynchronous relative to TTS / voice capture reopen

#### Scenario: Non-blocking voice path

- **WHEN** internalization is enqueued after a voice turn
- **THEN** the voice path SHALL reopen follow-up or dismiss without waiting for mem0 infer to finish

#### Scenario: Tool outcomes visible to voice

- **WHEN** Hermes or daily_assistant completes a successful turn
- **THEN** the system SHALL internalize facts into the worker lane and mirror a chat-lane copy so subsequent voice `recall` can surface them

### Requirement: Episode log

The agent-orchestrator SHALL append one structured episode per `/chat` (and stream-equivalent) turn including at least: timestamp, session_id, route/target, mode, truncated user text, truncated reply, end_session flag, latency class, and outcome (ok|error|timeout).

#### Scenario: Doctor can report learning health

- **WHEN** `aipc doctor` (or portal health) checks self-improvement
- **THEN** it SHALL report whether episode logging is writable and the age of the last successful mem0 infer (or “never”)

### Requirement: Session-end consolidation

- **WHEN** `end_session` is true (farewell / explicit close)
- **THEN** the system SHALL enqueue consolidate of short-term history into mem0 before clearing the short-term buffer

#### Scenario: Farewell clears short-term only after flush

- **WHEN** the user says a farewell utterance
- **THEN** short-term turns for that session are cleared only after consolidate is enqueued (best-effort; failure SHALL NOT block the farewell reply)

### Requirement: Async critique job

The system SHALL provide an idle/low-load job that samples recent episodes and produces structured lessons (preferences, tool habits, optional STT repair candidates, routing few-shots).

#### Scenario: Few-shot bank update

- **WHEN** the critique job finds the same tool habit at least three times with consistent target
- **THEN** it MAY append a routing few-shot entry to the versioned few-shot bank used by the intent classifier

#### Scenario: No silent thr mutation

- **WHEN** the critique job suggests VAD / follow-up silence / energy threshold changes
- **THEN** it MUST NOT apply them automatically; it SHALL only record a proposal for human or OpenSpec application

### Requirement: Model-first daily routing

Daily-assistant detection for ordinary productivity intents SHALL be performed by the model classifier (or equivalent multimodal LLM route), not by a closed keyword if/else list as the sole gate.

#### Scenario: Novel phrasing still routes

- **WHEN** the user asks for calendar/email/search/usage with phrasing not present in any static keyword list
- **THEN** the classifier model path SHALL still be eligible to select `daily_assistant` under its timeout policy

### Requirement: Safety envelope

Self-improvement SHALL NOT:

- Fine-tune or replace production model weights without a separate explicit change and user opt-in
- Widen tool permission grants automatically
- Upload episodes or memories off-box
- Edit `modules/**` or systemd unit files automatically

#### Scenario: Risky self-edit blocked

- **WHEN** a critique proposes modifying repository modules or enabling a new risky tool
- **THEN** the system SHALL refuse auto-apply and record the proposal in the safety ledger only
