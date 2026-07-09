## ADDED Requirements

### Requirement: Turns pass through a modular aggregator
User turns SHALL be handled by a modular aggregator that owns mode state,
context assembly, control (local model and/or keywords), allow-listed
action execution, backend routing (`local` vs `online`), output, and
aggregated status. Entry adapters and feature packs SHALL register on the
aggregator and SHALL NOT implement a parallel full turn pipeline that
bypasses it. Optional packs SHALL compose with core slots in one turn
when control requests multiple actions.

#### Scenario: Pack uses shared session not a second browser
- **WHEN** an optional pack that needs the web client runs during an
  online turn
- **THEN** it operates on the same online backend session as Voice and
  inject, not a second independent browser profile by default

#### Scenario: Status is aggregated
- **WHEN** the user requests assistant status
- **THEN** status is produced by the aggregator and includes mode plus
  health of registered backends/slots so local and online are one product

#### Scenario: Control and backend both run in one turn
- **WHEN** control selects a mode or session action and a user message
  remains to fulfill
- **THEN** the aggregator executes actions then routes the message to the
  appropriate backend without requiring a second user entry invocation

### Requirement: Unified entry accepts text and voice
The system SHALL provide a unified entry into the aggregator that accepts
both text input and voice-derived text (after STT). Text modality SHALL
NOT require microphone capture. When mode is `online` and modality is
`text`, the aggregator SHALL route to the online backend to inject and
send the user text (and MAY scrape the reply). When mode is `online` and
modality is `voice`, the default SHALL remain path B (inject context then
ChatGPT Voice) unless configured otherwise.

#### Scenario: Text turn in local mode
- **WHEN** mode is `local` and the user submits text via the unified entry
- **THEN** the aggregator uses the local agent chat backend without STT

#### Scenario: Text turn in online mode
- **WHEN** mode is `online` and the user submits text via the unified entry
- **THEN** the aggregator injects and sends the text through the online
  web backend without requiring Voice to start

#### Scenario: Voice adapter reuses the aggregator
- **WHEN** the user triggers push-to-talk
- **THEN** STT output is submitted to the aggregator with voice modality
  rather than a separate online-only pipeline that bypasses the hub

### Requirement: Assistant mode defaults to local
The system SHALL persist an assistant mode value of either `local` or
`online`. The default on a fresh install or missing mode file SHALL be
`local`. Switching mode SHALL be possible via a documented CLI without
rebuilding the image.

#### Scenario: Fresh system is local
- **WHEN** no assistant mode file exists
- **THEN** effective mode is `local`

#### Scenario: User enables online mode
- **WHEN** the user runs the documented mode CLI to set `online`
- **THEN** subsequent mode reads return `online` until changed again

### Requirement: Online mode uses subscription web client not platform API
When mode is `online`, the online-assistant surface SHALL drive an
**aipc-owned Chromium-family web engine wrapper** loaded with
`https://chatgpt.com/` (or a documented successor URL) using a dedicated
profile directory owned by the module. The surface SHALL NOT require an
OpenAI platform API key and SHALL NOT send voice audio through LiteLLM or
`api.openai.com` Realtime endpoints for this path.

#### Scenario: Online turn does not call Realtime API
- **WHEN** an online Voice turn is started with no `OPENAI_API_KEY` set
- **THEN** the turn still attempts to use the web client session and does
  not fail solely due to missing platform API credentials

### Requirement: Default runtime does not depend on system Google Chrome
The default online-assistant launch path SHALL use the module-provided or
module-pinned Chromium engine and profile, and SHALL NOT require Flatpak
`com.google.Chrome`, host `google-chrome`, or attaching to the user's
everyday browser session. An optional config override may point at an
external browser binary for debugging only.

#### Scenario: Online turn without system Chrome package
- **WHEN** system Google Chrome is not installed and the module engine is
  available
- **THEN** an online turn can still launch the wrapper against the
  dedicated profile

### Requirement: Automation control plane is loopback-only
The bridge SHALL bind any remote-debugging or automation port (CDP or
equivalent) only to `127.0.0.1` (or equivalent loopback). The bridge
SHALL refuse to start if configuration would expose the control port on a
non-loopback address.

#### Scenario: Non-loopback bind is rejected
- **WHEN** configuration requests a control-port bind address other than
  loopback
- **THEN** the bridge exits non-zero with a one-line diagnosis and does
  not launch the engine with that configuration

### Requirement: Online path B injects context then starts Voice
An online turn SHALL (1) ensure the web client window/session is
available, (2) inject a session context bundle into the client when the
session is new or the bundle is stale per policy, and (3) attempt to
start ChatGPT Voice mode. Path B is the default online UX.

#### Scenario: Successful online turn starts Voice after inject
- **WHEN** mode is `online`, the user is logged into the profile, and
  Voice controls are available
- **THEN** the bridge injects context (or skips inject when still fresh)
  and starts Voice without requiring the user to manually open the
  browser first

#### Scenario: Missing login is a soft failure
- **WHEN** mode is `online` but the profile is not authenticated
- **THEN** the turn fails with a user-visible notification and does not
  hang indefinitely

### Requirement: Session context bundle is minimal and soft-failing
The v0 session context bundle SHALL include at least local datetime (with
timezone) and, when available, the configured voice/assistant persona
name. Optional mem0 facts MAY be included; if mem0 is unreachable the
inject SHALL still proceed with the available fields. The bundle SHALL
be plain text suitable for pasting into the web client.

#### Scenario: Mem0 down still injects
- **WHEN** session inject runs and mem0 does not respond within its
  timeout
- **THEN** inject still delivers datetime (and persona name if configured)
  without aborting the online turn solely due to mem0

### Requirement: Transcript watcher reports live or degraded
While Voice is active, the bridge SHALL attempt to observe conversation
transcript text from the web client. Status SHALL expose transcript
health as `live` or `degraded`. Keyword automation that depends on
transcript SHALL run only when health is `live`.

#### Scenario: Scrape failure degrades without killing local mode
- **WHEN** transcript nodes cannot be read for a configured grace period
- **THEN** transcript health becomes `degraded`, keyword rules stop
  firing, and assistant mode is left unchanged

### Requirement: Keyword rules drive stop and mode actions
The system SHALL load keyword rules from a YAML config (system default
plus optional user override). Matching SHALL default to **user** role
transcript events only unless a rule explicitly allows another role.
Supported actions for v0 SHALL include at least: `voice_stop`,
`mode_local`, `session_close`, and `inject_session`. Rules SHALL support
a cooldown interval to prevent repeat firing.

Default end-related phrases (user-overridable) SHALL map so that
ordinary "結束／關掉語音／結束通話" class commands close the ChatGPT
client window, not only stop Voice UI. Concretely, the shipped default
rules SHALL treat end-session phrases as `session_close` (or
`mode_local` which includes window close — see below), not bare
`voice_stop` alone.

#### Scenario: User says end-voice phrase
- **WHEN** transcript health is `live` and a user transcript contains a
  configured end-session / end-voice phrase outside cooldown
- **THEN** the bridge stops Voice if active and closes the ChatGPT
  client window (page/app window via CDP or equivalent)

#### Scenario: User says return-to-local phrase
- **WHEN** transcript health is `live` and a user transcript contains a
  configured return-to-local phrase outside cooldown
- **THEN** the bridge stops Voice if active, closes the ChatGPT client
  window, and sets assistant mode to `local`

#### Scenario: Assistant transcript does not trigger user-only rules
- **WHEN** a rule is `on: user` and only the assistant transcript contains
  the phrase
- **THEN** the action does not fire

### Requirement: session_close closes the client window
The `session_close` action SHALL close the dedicated online-assistant
wrapper window (or page) for the module profile. After a successful close,
the automation endpoint MAY become unavailable until the next online turn
restarts the wrapper. Closing SHALL NOT wipe the dedicated profile
directory (cookies/login persist).

#### Scenario: session_close tears down wrapper window
- **WHEN** `session_close` runs against a live online-assistant wrapper
  session
- **THEN** the ChatGPT window is closed and a subsequent connect to the
  previous control port fails or reports no ChatGPT page until relaunch

### Requirement: Idle and max session timeouts stop Voice
The bridge SHALL stop Voice when no new transcript events arrive for a
configured idle interval while Voice is active, and SHALL stop Voice when
a single Voice session exceeds a configured maximum duration. Timeouts
SHALL work even when transcript health is `degraded` if the bridge can
still detect that Voice UI is active; if Voice activity itself cannot be
detected, the bridge SHALL still enforce max wall-clock duration from
`voice_start`.

#### Scenario: Idle timeout stops Voice
- **WHEN** Voice has been active and no transcript event arrives for
  `idle_stop_s`
- **THEN** the bridge issues `voice_stop` and notifies the user

#### Scenario: Max session timeout stops Voice
- **WHEN** Voice has been active longer than `max_session_s`
- **THEN** the bridge issues `voice_stop` regardless of recent transcript

### Requirement: Module is optional until hardware-verified
The `assistant-chatgpt` module SHALL ship disabled or otherwise
non-mandatory so that hosts without a ChatGPT login or without the
bundled engine remain healthy. `verify.sh` SHALL exit `0` on pass, `2`
when the feature is intentionally optional/disabled, and other non-zero
on hard failure of installed/enabled checks.

#### Scenario: Disabled module is optional to doctor
- **WHEN** the module is disabled and `verify.sh` is run
- **THEN** the script exits `2` with a one-line optional diagnosis

### Requirement: Feature packs are modular and independently toggleable
The online-assistant implementation SHALL separate **core** capabilities
(engine, session, inject, transcript, keywords, voice controls, actions)
from **optional feature packs** (including at least placeholders or docs
for handoff, system-audio, project, gpt, upload, canvas, capture, and
tasks). Optional packs SHALL be disableable via configuration without
removing core Voice/inject/session_close. A disabled or missing optional
pack SHALL NOT break core turns; commands for that pack SHALL fail with a
clear diagnosis.

#### Scenario: Core turn works with optional packs off
- **WHEN** only core packs are enabled and the user runs an online Voice
  turn with inject and session_close
- **THEN** the turn succeeds without requiring project, gpt, canvas, or
  system-audio packs

#### Scenario: Disabled pack command fails soft
- **WHEN** the project pack is disabled and the user invokes a project
  open command
- **THEN** the CLI exits non-zero with a one-line diagnosis and does not
  crash the core bridge

### Requirement: Local model controller selects allow-listed actions
The system SHALL support a controller that classifies user-side STT or
transcript text via the LiteLLM gateway using a local model alias
(default `resident-small`, configurable to another local alias). The
controller SHALL emit only allow-listed actions (including `none`,
`session_close`, `mode_local`, `mode_online`, `voice_stop`, and documented
feature-pack runs). The controller SHALL NOT invoke cloud model aliases by
default and SHALL NOT execute free-form shell from model output.

#### Scenario: Controller uses LiteLLM local alias
- **WHEN** the controller is enabled and classifies a transcript event
- **THEN** the inference request is sent to the LiteLLM gateway with a
  local model alias such as `resident-small` and not to a cloud alias by
  default

#### Scenario: Unknown action is ignored
- **WHEN** the model returns an action name outside the allow list
- **THEN** the system treats the decision as `none` and does not perform
  an arbitrary command

### Requirement: Keyword rules remain fallback for the controller
The system SHALL fall back to deterministic keyword rules when the
controller is disabled, unreachable, times out, returns invalid output,
or reports confidence below a configured threshold. Keyword-only
operation SHALL remain sufficient for core end-session behavior.

#### Scenario: LiteLLM down still ends session on keyword
- **WHEN** the controller cannot reach LiteLLM and the user transcript
  matches a configured end-session keyword
- **THEN** `session_close` (or the configured end action) still runs

### Requirement: No default mem0 write-back of ChatGPT transcripts
The system SHALL NOT write ChatGPT online transcripts into mem0 unless
an explicit configuration flag enables write-back. Default SHALL be off.

#### Scenario: Default config does not remember online chat
- **WHEN** an online Voice session ends and write-back is left at default
- **THEN** no mem0 add/remember call is made for that session transcript

### Requirement: Default capture is microphone only
The online-assistant wrapper SHALL default to microphone-only input for
ChatGPT Voice. Enabling additional system/desktop audio capture SHALL
require an explicit allow (configuration and/or per-session grant) and
SHALL NOT turn on solely because assistant mode is `online`.

#### Scenario: Online mode alone does not share system audio
- **WHEN** the user sets mode to `online` and starts Voice without any
  system-audio allow
- **THEN** the capture path remains microphone-only

### Requirement: System audio share excludes assistant own playback
When system/desktop audio share is allowed, the capture mix SHALL include
other applications' audio intended for the user and SHALL NOT include the
online-assistant wrapper's own speech/playback output (ChatGPT Voice TTS
or equivalent), so the model does not hear itself.

#### Scenario: Allow system share keeps self-voice out of input
- **WHEN** system-audio share is active and the wrapper is playing ChatGPT
  Voice audio to the default speakers
- **THEN** that playback is not routed into the wrapper's capture source
  used as the browser microphone

### Requirement: System audio allow is visible and revocable
When system-audio share is active, status output SHALL indicate that it is
active. Session-scoped allows SHALL end on `session_close` or explicit
revoke. Sticky allows SHALL remain configurable but documented as higher
privacy risk.

#### Scenario: Session close clears session-scoped system share
- **WHEN** system-audio share was granted for the current session only and
  `session_close` runs
- **THEN** system-audio share is no longer active for the next online turn
  until allowed again
