## ADDED Requirements

### Requirement: Wake → STT → LLM → TTS Pipeline (Path A Default)

The `voice-pipecat` module SHALL ship a Pipecat pipeline that ingests
microphone audio, gates on wake-word detection, routes the captured
utterance through an STT service, sends the transcribed text to Phase
4's `POST /chat`, and synthesises the reply through a TTS service.
This SHALL be the default pipeline (path A). A multimodal-first
variant (path B, Qwen2.5-Omni) SHALL be wireable as an alternate
Pipecat pipeline config but SHALL NOT be the shipping default until
Open Question Q1 (gfx1151 viability) is resolved.

#### Scenario: Default pipeline is path A

- **WHEN** the image is freshly deployed and `aipc agent voice
  settings show` is run
- **THEN** the printed pipeline is `path-a` (wake → STT → LLM → TTS)
  and `path-b` is listed as available-but-disabled

#### Scenario: End-to-end voice round trip works

- **WHEN** the user says the wake word followed by a short query and
  the Phase 4 `/chat` endpoint is live
- **THEN** Pipecat's trace shows wake detection → STT transcript →
  `POST /chat` call → TTS synthesis → audio out, and the reply audio
  is heard within the latency budget defined by the deployed Pipecat
  pipeline config

---

### Requirement: Custom Wake Word Trained On-Device

The `voice-wake` module SHALL load a wake-word model from
`/var/lib/aipc-voice/wake/<phrase>.onnx` and run inference on the
NPU. The model SHALL be trained at firstboot from 3–5 user-recorded
samples by the firstboot wizard (jointly owned with Phase 7
`ops-firstboot`). NPU inference SHALL be always-on at low power; no
cloud round-trip SHALL occur in the training or inference path. The
detection threshold SHALL be exposed in `aipc agent voice settings`.

#### Scenario: Training writes an ONNX model from user samples

- **WHEN** the firstboot wizard's wake-word screen completes with 3–5
  recorded samples
- **THEN** an ONNX model file appears at
  `/var/lib/aipc-voice/wake/<phrase>.onnx` whose label matches the
  user-supplied phrase

#### Scenario: Wake word inference runs on the NPU

- **WHEN** `voice-wake.service` is active and `xdna-smi` is queried
- **THEN** the NPU shows non-idle utilisation attributable to the
  wake-word process while the microphone is hot

#### Scenario: No network egress during wake-word training

- **WHEN** the firstboot wake-word screen runs with network
  monitoring active
- **THEN** no outbound connections originate from the training
  process

---

### Requirement: STT Pair Routed By Utterance Length

The `voice-stt-sensevoice` and `voice-stt-paraformer` modules SHALL
both ship as systemd services exposing HTTP `/healthz` and
`/transcribe` endpoints. Pipecat SHALL dispatch each captured
utterance to a router (`router-1b` LiteLLM alias) which emits a
length classification, then SHALL send the audio to SenseVoice for
utterances shorter than 10 seconds and to Paraformer for longer or
streaming utterances. Neither service SHALL be invoked outside the
routing step.

#### Scenario: Both STT services healthy after boot

- **WHEN** the image is freshly deployed and both services are
  expected to be active
- **THEN** `curl http://127.0.0.1:8101/healthz` (SenseVoice) and
  `curl http://127.0.0.1:8102/healthz` (Paraformer) both return HTTP
  200

#### Scenario: Short utterance hits SenseVoice

- **WHEN** Pipecat captures an utterance <10 s and the router
  classifies it as short
- **THEN** the transcribe request lands at the SenseVoice service,
  not Paraformer (verifiable in Pipecat's trace and the SenseVoice
  access log)

#### Scenario: Long utterance hits Paraformer

- **WHEN** Pipecat captures a continuous utterance ≥10 s
- **THEN** the transcribe request lands at the Paraformer service
  (verifiable in Pipecat's trace and the Paraformer access log)

---

### Requirement: TTS Pair Routed By Language

The `voice-tts-cosyvoice` and `voice-tts-kokoro` modules SHALL both
ship as systemd services exposing HTTP `/healthz` and `/synthesise`
endpoints. Pipecat SHALL route Chinese replies to CosyVoice 2 and
English replies to Kokoro using the language tag already produced
during the STT routing step. CosyVoice 2 SHALL accept a reference
sample path for zero-shot voice cloning when one is configured by the
firstboot wizard; otherwise it SHALL use the user-selected preset.

#### Scenario: Both TTS services healthy after boot

- **WHEN** the image is freshly deployed
- **THEN** `curl http://127.0.0.1:8111/healthz` (CosyVoice) and
  `curl http://127.0.0.1:8112/healthz` (Kokoro) both return HTTP 200

#### Scenario: Chinese reply routes to CosyVoice 2

- **WHEN** Phase 4 returns a Chinese-language reply text
- **THEN** the synthesise request lands at the CosyVoice 2 service,
  carrying the cloning-sample path if `/var/lib/aipc-voice/persona/clone.wav`
  exists

#### Scenario: English reply routes to Kokoro

- **WHEN** Phase 4 returns an English-language reply text
- **THEN** the synthesise request lands at the Kokoro service

---

### Requirement: Persona Configured At Firstboot

The image SHALL ship without an assistant name or default voice. The
firstboot wizard's persona screen (jointly owned with Phase 7
`ops-firstboot`) SHALL capture: (a) assistant name (free-form
string, used as the wake-word training label), (b) voice choice
(preset from `female-zh`, `neutral-zh`, `female-en`, or "record your
own"), and (c) when "record your own" is chosen, a 5–10 s reference
sample stored at `/var/lib/aipc-voice/persona/clone.wav`. The
captured name SHALL be written to `/etc/aipc/voice/persona.yaml`.

#### Scenario: No baked persona on a fresh image

- **WHEN** the image is freshly deployed and the firstboot wizard has
  not yet run
- **THEN** `/etc/aipc/voice/persona.yaml` does not exist and
  `/var/lib/aipc-voice/persona/clone.wav` does not exist

#### Scenario: Persona file populated after firstboot

- **WHEN** the firstboot wizard's persona screen completes with a
  user-chosen name and voice preset
- **THEN** `/etc/aipc/voice/persona.yaml` contains the chosen name and
  preset key

#### Scenario: Cloning sample preserved when chosen

- **WHEN** the firstboot wizard's persona screen completes with a
  recorded 5–10 s sample
- **THEN** the sample is stored at
  `/var/lib/aipc-voice/persona/clone.wav` and CosyVoice 2 uses it on
  subsequent synthesise calls

---

### Requirement: Push-To-Talk Hotkey

The `voice-pipecat` module SHALL register a GNOME custom keybinding
mapping `Super+Space` to `aipc agent voice force-wake`. The
force-wake command SHALL emit a synthetic wake event to Pipecat that
bypasses the wake-word classifier and treats the next captured audio
window as wake-confirmed. The binding SHALL be rebindable via `aipc
agent voice settings`.

#### Scenario: Default binding registered

- **WHEN** the image is freshly deployed and `gsettings get
  org.gnome.settings-daemon.plugins.media-keys custom-keybindings`
  is queried for the AIPC voice binding
- **THEN** a binding entry exists with `binding=<Super>space` and
  `command=aipc agent voice force-wake`

#### Scenario: Force-wake bypasses the classifier

- **WHEN** the user presses `Super+Space`
- **THEN** Pipecat's trace shows a synthetic wake event followed by
  STT capture, with no wake-word inference run

---

### Requirement: Listen-Off Triggers Gate Wake-Word Inference

The `voice-pipecat` module SHALL ship a `aipc-voice-mute.target`
systemd target activated by any of: (a) GNOME screen lock (via the
`org.gnome.ScreenSaver.ActiveChanged` DBus signal), (b) voice command
`mute` or `DND` recognised by the Daily Assistant sub-agent, or (c)
GNOME Do-Not-Disturb toggle (via the same DBus surface).
`voice-wake.service` SHALL declare `BindsTo=!aipc-voice-mute.target`
so that any active trigger pauses NPU wake-word inference.

#### Scenario: Screen lock pauses wake-word inference

- **WHEN** the GNOME screen lock activates
- **THEN** `systemctl is-active aipc-voice-mute.target` returns
  `active` and `voice-wake.service` reports paused (no NPU
  utilisation from the wake-word process)

#### Scenario: Voice command pauses wake-word inference

- **WHEN** the user says the wake word followed by `mute`
- **THEN** the Daily Assistant routes to the mute action,
  `aipc-voice-mute.target` becomes active, and wake-word inference
  pauses

#### Scenario: GNOME DND pauses wake-word inference

- **WHEN** the user enables GNOME Do-Not-Disturb
- **THEN** `aipc-voice-mute.target` becomes active and wake-word
  inference pauses

---

### Requirement: Command Vs Chat Routing

The Pipecat pipeline SHALL classify each STT transcript via the
`router-1b` LiteLLM alias as either `cmd` or `chat`. `cmd`
transcripts SHALL route directly to the Phase 4 Daily Assistant
sub-agent via its short HTTP endpoint. `chat` transcripts SHALL
route to the Phase 4 supervisor via `POST /chat`. The classifier
SHALL be a prompt-only call (no per-deployment retraining
required).

#### Scenario: Short imperative routes to Daily Assistant

- **WHEN** the STT transcript is "what time is it" (or an equivalent
  short imperative)
- **THEN** router-1b emits `cmd` and the request lands at the Daily
  Assistant sub-agent endpoint, not the supervisor `/chat`

#### Scenario: Conversational query routes to supervisor

- **WHEN** the STT transcript is a multi-sentence conversational
  query
- **THEN** router-1b emits `chat` and the request lands at `POST
  /chat`

---

### Requirement: Voice → Agent Interface Via HTTP POST /chat

The `voice-pipecat` module SHALL communicate with the Phase 4 agent
runtime exclusively via the text `POST /chat` interface declared by
Phase 4 D10 (and the Daily Assistant short-command endpoint for
`cmd` routing). Pipecat SHALL NOT import LangGraph, SHALL NOT share
runtime state with the agent process, and SHALL NOT open a websocket
to the agent in v1.

#### Scenario: Pipecat does not import LangGraph

- **WHEN** `grep -rE '^(import|from) langgraph\\b'
  modules/voice-*/` is run
- **THEN** the command exits non-zero (no matches found)

#### Scenario: All agent calls go through HTTP

- **WHEN** Pipecat dispatches a `chat` transcript and the agent
  process logs its incoming requests
- **THEN** the request appears in the HTTP access log for `/chat`
  with a text body, not via any other channel

---

### Requirement: LiteLLM Is The Only LLM Endpoint For Voice Routing

All voice-side LLM calls SHALL go through the Phase 1 LiteLLM gateway at `http://127.0.0.1:4000`. This covers the Pipecat router step (`router-1b` classification) and any future voice-side LLM call. No voice module SHALL declare a direct
backend URL (Ollama on `:11434`, Lemonade on `:8001`, vLLM on
`:8000`) or any cloud LLM URL. This requirement cross-references
`CLAUDE.md §7`.

#### Scenario: No direct backend URL in any voice module config

- **WHEN** `grep -rE
  '(api\\.openai\\.com|api\\.anthropic\\.com|generativelanguage\\.googleapis\\.com|127\\.0\\.0\\.1:(11434|8001|8000))'`
  is run against `modules/voice-*/files/`
- **THEN** the command exits non-zero (no matches found)

#### Scenario: Router call hits LiteLLM

- **WHEN** Pipecat classifies an STT transcript
- **THEN** the request to `http://127.0.0.1:4000/v1/chat/completions`
  carries `"model": "router-1b"`
