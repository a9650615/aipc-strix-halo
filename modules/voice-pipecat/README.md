# voice-pipecat

## Current status: v0 push-to-talk, text-out — disabled pending STT hardware verification

This is a deliberately reduced scope, not the full Phase 3 design: **no
TTS, no wake word, no hotkey**. The user's explicit direction was "text
output is fine, the assistant does not need to speak yet." What's here is
a manually-invoked one-shot round trip: record -> transcribe -> ask the
agent -> show the reply as a desktop notification.

### What it does (v0)

`files/usr/bin/aipc-voice-once` — a single stdlib-only Python script, no
systemd unit, invoked manually from a terminal (or a keyboard-shortcut
launcher a user sets up themselves; no hotkey is registered by this
module):

1. Records N seconds of audio (default 5, `--seconds` or
   `$AIPC_VOICE_RECORD_SECONDS`) from the default ALSA input via
   `arecord -f S16_LE -r 16000 -c 1` — no Python audio library dependency.
2. `POST`s the WAV to the STT service (assumed contract below).
3. `POST`s the transcribed text to agent-orchestrator's `/chat`
   (`http://127.0.0.1:4100/chat`, real and hardware-verified — see
   `modules/agent-orchestrator`).
4. Shows the reply via `notify-send` (falls back to stdout if
   `notify-send` isn't present).

Run it directly: `aipc-voice-once` (or `aipc-voice-once --seconds 8` for a
longer recording). `--self-test` runs offline checks only (used by
`verify.sh`).

### Why plain Python, not `pipecat-ai`

`pipecat-ai` (confirmed real, latest `1.5.0` on PyPI) is a framework for
streaming, multi-stage audio pipelines with frame processors — built for
exactly the full D1 pipeline (wake -> STT-router -> LLM -> TTS-router)
this module will eventually run. That pipeline doesn't exist yet on
either end: no wake service, no TTS service, and the STT service itself
is still scaffold-only. For a 4-step blocking round trip (record, two
HTTP POSTs, notify), wrapping it in pipecat-ai's pipeline/frame API would
be more code than the problem, not less — boring-over-clever per this
repo's own ethos. Revisit `pipecat-ai` once the streaming pieces (wake
word, TTS, barge-in) are actually being built; the pip package stays a
reasonable choice for that later work.

### Assumed STT interface contract (for reconciliation)

`voice-stt-sensevoice` (port 9001) is being built separately and, as of
this writing, has no `server.py` yet — only a scaffold. This module
assumes:

```
POST http://127.0.0.1:9001/transcribe
Request:  raw WAV bytes as the request body, Content-Type: audio/wav
          (16 kHz mono S16_LE — what arecord above produces)
Response: 200 {"text": "..."}
```

Chosen over a `multipart/form-data` file upload for simplicity on both
ends (no boundary parsing). If the real `voice-stt-sensevoice` server
ships a different shape (e.g. multipart `UploadFile`, a different sample
rate, a JSON-wrapped base64 body), reconcile by updating `transcribe()`
in `aipc-voice-once` — it's the only place that assumption lives.

### Deferred (not this dispatch)

- TTS (CosyVoice 2 / Kokoro) — replaced by `notify-send` text-out per
  explicit user direction. Tasks 4.x, D5.
- NPU wake-word classifier/training pipeline — task group 2, a separate,
  more complex piece. `modules/voice-wake` doesn't exist yet.
- Global hotkey (`Super+Space` push-to-talk, D6) — GNOME keybinding
  registration is real desktop-integration complexity; tasks 1.2/2.x/7.1
  are all still open. `aipc-voice-once` must be invoked manually (a
  terminal alias or a user-configured keybinding calling it is a
  reasonable stopgap, not shipped here).
- The full path-A pipeline config (`files/etc/aipc/pipecat/pipeline.yaml`)
  describes the eventual wake/STT-router/LLM/TTS-router shape and is left
  in place untouched — it is not read by `aipc-voice-once` and does
  nothing in v0.
- `aipc-voice-mute.target` (D7 listen-off triggers) is left in place
  untouched. It has no dependents today (nothing else in this repo
  references it) and isn't wired into anything by this v0 — legitimate
  future scope for when the wake-word service exists.
- LangGraph/multi-agent routing inside voice-pipecat itself (task 5.3/5.4)
  — this v0 always calls the supervisor's `/chat`, never a direct
  Daily-Assistant shortcut.

### Verification reached

- **Static**: `verify.sh` runs `ast.parse` on `aipc-voice-once` plus
  `aipc-voice-once --self-test` (offline: URL defaults, JSON response
  parsing, arg parsing).
- **Render-verified**: `tools/aipc render bootc` / `render ansible` both
  succeed; the module is `.disabled`, so it's correctly excluded from
  both renders (same as before this change) — this only confirms the
  render pipeline itself doesn't choke on the module's other files.
- **Partial hardware-verified (2026-07-06)**, on the real AI PC:
  - `arecord -f S16_LE -r 16000 -c 1 -d 2 ...` recorded real audio from
    the machine's `HD-Audio Generic ALC294` capture device.
  - Running `aipc-voice-once --seconds 2` end-to-end: recording
    succeeded, then failed cleanly at the STT step with
    `STT service unreachable at http://127.0.0.1:9001/transcribe:
    Connection refused` (expected — no real STT service exists yet) and
    a non-zero exit, not a crash.
  - `chat()` and `show()` were exercised directly (loaded as a module,
    bypassing the STT step) against the live
    `aipc-agent-orchestrator.service`: `POST /chat {"text": "reply with
    exactly: pong"}` returned `{"text": "pong", ...}`; `show("pong")`
    called `notify-send` (`which notify-send` confirms present; the
    call exited 0 with a live DBus session/`DISPLAY` on this machine).
  - **Not** verified: the full round trip through a real STT response,
    since no real STT service exists yet. Module stays `.disabled` until
    that's true and a real end-to-end recording is confirmed.

## Dependencies

- `llm-litellm` / agent-orchestrator's `/chat` — reused as-is, not
  touched by this change.
- `voice-stt-sensevoice` — assumed contract above; being built in
  parallel, not touched by this change.
- `alsa-utils` (provides `arecord`), `libnotify` (provides `notify-send`)
  — declared in `packages.txt`, both already present on this dev/build
  machine, verified installed via the image's package set for the target
  build.

## Spec

- `openspec/changes/phase-3-voice/design.md` — D9 (text in, text out to
  `/chat`). D1, D2, D5, D6, D7, D8 are explicitly out of scope here.
- Tasks 1.1, 5.1, 5.2 (this v0's slice); 1.2, 2.x, 4.x, 5.3, 5.4, 6.x,
  7.2–7.5 remain open.
