## Why

Local voice (SenseVoice → `:4100` → CosyVoice/Kokoro) stays the offline default,
but ChatGPT subscription Voice (GPT-Live class) is markedly more natural and the
user already pays for it. They need that client experience **bound into aipc**
as an explicit **online assistant mode**: same hotkey/side-button entry, local
context injected into the ChatGPT web session, and **transcript-driven
automation** (keyword stop, return-to-local, idle timeout)—without OpenAI API
spend and without replacing the local stack.

**Prime premise:** every capability in this change (wrapper, packs, local
controller, system audio, handoff, web-only surfaces) MUST **mutually
integrate**—shared mode, session, actions bus, status, and aipc context—
not ship as isolated demos that cannot hand off to each other.

## What Changes

- **Modular super-aggregator in the middle**: all turns pass through an
  aggregator hub (pipeline: entry → context → control → actions →
  backend.local|online → output). Slots/packs register; nothing important
  bypasses the hub. Code boundary: aggregator vs online backend (may be
  one or two `modules/*` trees; interfaces stay separate).
- **Unified entry point**: text (`--text`/stdin) and voice (PTT/STT
  adapter) both produce `TurnRequest` into the aggregator; modality is a
  parameter (online text = inject+send; online voice = path B).
- **Online backend module `assistant-chatgpt`**: aipc-owned Chromium
  wrapper for `chatgpt.com` (pinned engine + isolated profile). Not system
  Chrome. Implements `backend.online` + web feature packs for the hub.
- **Local small-model controller slot**: LiteLLM `resident-small` (optional
  `qwythos-9b` / `assistant-gemma`) → allow-listed actions; keywords
  fallback; no cloud on control plane by default.
- **Assistant mode state**: `local` (default) | `online`, readable by
  `aipc-voice-once` / future Pipecat entrypoints; CLI
  `aipc assistant mode …`.
- **Path B (shipping default for online)**: session context inject → start
  ChatGPT Voice → hand conversation to the subscription client.
- **Transcript watcher**: best-effort scrape of live captions / chat bubbles
  during Voice; status `live` | `degraded`.
- **Keyword rules engine**: user-utterance keywords trigger actions
  (`voice_stop`, `mode_local`, `session_close`, `inject_session`,
  `inject_delta`); cooldown and user-side-only matching by default.
  **End-related phrases default to closing the ChatGPT app window**
  (`session_close` / `mode_local`), not only stopping Voice UI.
- **Timeouts**: idle-no-transcript and max session auto `voice_stop`
  (window-close on idle/max is configurable; end keywords close window).
- **Headed first; headless later**: v0 is headed wrapper window + automation
  API. Future optional virtual-display / headless-ish mode is deferred
  (true engine `--headless` is a poor fit for Voice).
- **Local → online spoken handoff (v1)**: while in local mode, configured
  STT phrases (e.g.「網上助理」「用 ChatGPT」) switch/start the online
  path and may inject the remainder of the utterance; reverse already
  planned via online keywords → `mode_local` + close window.
- **Context packing (v0 minimal)**: persona name, datetime, short mem0
  summary; optional topic deltas later via `:4100/context`.
- **Privacy defaults**: online mode is explicit opt-in; mem0 write-back of
  ChatGPT transcripts **off** unless configured; control port bound to
  `127.0.0.1` only.
- **Optional system-audio share (v1)**: when explicitly allowed, feed
  desktop/system audio into the wrapper capture mix **excluding** the
  assistant's own playback (no self-echo); default remains mic-only.
- **Docs**: `docs/voice-pipeline.md` (or sibling) documents online mode,
  degraded behavior, and non-goals.

## Capabilities

### New Capabilities

- `online-assistant`: Opt-in surface that drives the ChatGPT **subscription
  web UI** inside an aipc-owned Chromium wrapper as an alternate assistant
  mode: context inject, Voice start/stop, transcript observation, keyword
  and timeout actions, mode toggle with the local voice path.

### Modified Capabilities

- `voice` (phase-3 delta if archived name differs — apply as delta under
  this change): push-to-talk / `aipc-voice-once` SHALL branch on assistant
  mode (`local` → existing STT→`/chat`→TTS; `online` → online-assistant
  path B). Local-only cloud-STT/TTS non-goal for the **local** path is
  unchanged; online mode is a separate, explicit capability.

## Non-Goals

- OpenAI Realtime / platform API billing as the voice transport.
- Exposing ChatGPT web scrape as a stable OpenAI-compatible HTTP API.
- Depending on the user's daily Google Chrome / Flatpak browser as the
  default automation host.
- WebKit/Tauri system WebView as the primary Voice engine (Chromium-family
  wrapper only for v0 Voice quality).
- Automatic silent failover from local to online on local failure.
- Guaranteed perfect transcript capture across ChatGPT DOM revisions
  (degraded mode is required behavior).
- Always-on silent capture of desktop audio without user allow.
- Full tool round-trip protocol (`[[AIPC_ACTION]]`) in v0.
- Changing LiteLLM model aliases or baking `OPENAI_API_KEY` for this path.
- Standalone ChatGPT launchers or packs that bypass shared mode, session,
  actions bus, or status (breaks mutual integration).

## Impact

- **New**: aggregator hub (`assistant-aggregator` / `assistant-core`) +
  online backend `assistant-chatgpt` (or co-located with clear packages);
  configs, verify, optional user-unit for online engine.
- **`modules/voice-pipecat/`**: `aipc-voice-once` becomes voice **entry
  adapter** into the aggregator.
- **`modules/agent-orchestrator/`** (v1 tasks): optional `POST /context`
  for bundle assembly; v0 may call mem0/persona files directly from the
  bridge with soft-fail.
- **`docs/voice-pipeline.md`**: online mode section.
- **User-visible default**: mode remains **`local`** until the user runs
  `aipc assistant mode online` (or equivalent). Enabling online implies
  network use and ChatGPT ToS; no new paid API requirement beyond an
  existing ChatGPT subscription in the browser profile.
- **Security**: control port loopback-only; no secrets in repo (session
  cookies live in the wrapper's dedicated profile under `/var/lib` or
  `$XDG_DATA_HOME`, not the user's main browser profile).
