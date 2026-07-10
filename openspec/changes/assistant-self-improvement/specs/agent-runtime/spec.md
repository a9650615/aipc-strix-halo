# agent-runtime (delta)

## ADDED Requirements

### Requirement: Chat lifecycle metadata

`POST /chat` responses SHALL include `end_session` (boolean) and SHOULD
include `session_id` of the bound session. When `end_session` is true,
voice clients SHALL treat the conversation as finished (no follow-up arm;
overlay may hide).

#### Scenario: Farewell ends multi-turn

- **WHEN** the user utters a farewell or explicit “done” close
- **THEN** `end_session` is true, the session is marked `done`, and
  short-term context is cleared after consolidation is enqueued

### Requirement: Session API

The orchestrator SHALL expose session inspection suitable for portal and
doctor, including list of non-done sessions and last activity line.

#### Scenario: List open sessions

- **WHEN** a client calls the sessions list endpoint
- **THEN** each open session includes `id`, `status`, and
  `last_activity` (or equivalent progress summary)

### Requirement: Activity progress push

Workers that run longer than a short chat turn (Hermes, long daily,
background jobs) SHALL publish progress into the shared activity path
used by overlay and notifications.

#### Scenario: Phase update

- **WHEN** a long worker enters a new named phase
- **THEN** session `last_activity` updates and UX surfaces may show it
  without waiting for the final reply

### Requirement: Learning hooks on workers

Respond, daily_assistant, hermes, coder, and screen_see success paths SHALL invoke continuous internalization (or an equivalent documented hook) for durable learning.

#### Scenario: Hermes success internalizes

- **WHEN** Hermes returns status ok with a non-empty reply
- **THEN** internalization is enqueued (not skipped by default)

## MODIFIED Requirements

### Requirement: Intent classification policy

Intent classification for daily-style work MUST prefer the model classifier over static daily keyword tables. Keyword fallback remains allowed only when the model is disabled, times out, or fails.

#### Scenario: Rules-only mode is non-default

- **WHEN** the system runs with default production settings for this change
- **THEN** `AIPC_CLASSIFIER` is not `rules` / `rules_only` as the sole daily gate
