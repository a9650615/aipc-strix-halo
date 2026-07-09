## ADDED Requirements

### Requirement: Push-to-talk is a voice adapter to the unified entry
The push-to-talk entrypoint SHALL capture audio, run STT, and submit the
transcript to the unified assistant turn entry with voice modality. That
entry SHALL honor assistant mode: `local` uses local agent `/chat` then
TTS; `online` uses the online-assistant path (default path B for voice).
The primary binary is `aipc-voice-once` or its documented successor.

#### Scenario: Local mode unchanged
- **WHEN** assistant mode is `local` and the user triggers push-to-talk
- **THEN** STT text is handled via the unified entry on the local agent
  chat path (not the ChatGPT web bridge)

#### Scenario: Online mode dispatches to bridge
- **WHEN** assistant mode is `online` and the user triggers push-to-talk
- **THEN** the unified entry starts an online-assistant Voice turn and
  does not require a successful local `/chat` completion for that turn

### Requirement: Online module absence fails soft to local path
The voice adapter SHALL fail soft when assistant mode is `online` but the
online-assistant module or bridge binary is not installed: notify the
user and exit non-zero without calling `/chat` as a silent substitute and
without reporting a successful online Voice session.

#### Scenario: Online requested but bridge missing
- **WHEN** mode is `online` and `aipc-chatgpt` (or equivalent) is not on
  `PATH`
- **THEN** push-to-talk exits non-zero with a one-line diagnosis and does
  not report a successful online Voice session

### Requirement: Local STT can hand off to online assistant on command phrases
The unified turn path (including voice-adapter STT text) SHALL support
optional local-to-online handoff: when handoff is enabled, it SHALL
inspect the turn text before or instead of a normal local `/chat`
completion; if the text matches a handoff phrase, it SHALL start an
online-assistant turn and SHALL NOT treat a missing local LLM reply as
failure for that handoff turn. When handoff is disabled (v0 default),
local turns SHALL ignore handoff phrases and behave as pure local mode.
Text modality turns SHALL use the same handoff rules as voice-derived
text.

#### Scenario: Handoff disabled leaves local path pure
- **WHEN** handoff is disabled and mode is `local` and the user says a
  phrase that would otherwise be a handoff trigger
- **THEN** the entrypoint still uses local STT → `/chat` → TTS

#### Scenario: Handoff phrase opens online Voice
- **WHEN** handoff is enabled, mode is `local`, the online bridge is
  installed, and the STT transcript matches a handoff phrase outside
  cooldown
- **THEN** the system starts an online-assistant Voice turn and notifies
  the user that online mode was engaged

#### Scenario: Remainder is available for inject
- **WHEN** handoff matches a phrase with a trailing user request (e.g.
  trigger plus topic)
- **THEN** the bridge receives the remainder (or full transcript) for
  context inject so the user need not fully repeat the request
