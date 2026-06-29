## Why

Phase 1 stood up the LLM gateway; Phase 4 ships the agent runtime with a
text-only `POST /chat` interface. Phase 3 is what makes the AI PC feel
like an assistant rather than a chatbox: a wake word the user trains
themselves, a Pipecat pipeline that turns speech into text and text back
into speech, a personalised TTS voice the user records, and the
listen-off triggers that keep the always-on microphone from leaking
audio when the user steps away.

The architecture decision is that voice is a *pluggable orchestration
layer* in front of the existing Phase 4 `/chat` endpoint, not a new
agent. The Pipecat pipeline is the only producer of the voice surface;
the agent runtime stays unchanged. Path A (STT → LLM → TTS) is the
shipping default; path B (multimodal-first, Qwen2.5-Omni) is an opt-in
v2 once hardware viability is proven on gfx1151.

## What Changes

- **New capability `voice`** covering the 6 Phase 3 modules as one
  coherent voice surface.
- **Pipecat as the orchestrator**: a single `voice-pipecat` module owns
  the pipeline graph (wake → STT → router → /chat → TTS) and the
  push-to-talk + listen-off control plane.
- **Custom wake word trained on-device**: firstboot wizard records 3–5
  user samples, trains a small ONNX classifier, ships the model to
  `voice-wake` for always-on NPU inference at low power.
- **Two STT services, length-routed**: SenseVoice-Small for <10s
  utterances (faster), Paraformer-zh-streaming for longer / dictation.
  router-1b picks per request.
- **Two TTS services, language-routed**: CosyVoice 2 for Chinese with
  zero-shot voice cloning of the user's recorded sample; Kokoro for
  English (lighter, native quality).
- **Persona configured at firstboot**: name (no default), voice
  (preset or cloned), wake-word samples — all captured by the same
  wizard.
- **Push-to-talk hotkey** at `Super+Space` by default, rebindable from
  `aipc agent voice settings`.
- **Listen-off triggers**: GNOME screen lock, voice command
  (mute/DND), and GNOME Do-Not-Disturb toggle each independently pause
  wake-word inference via the `aipc-voice-mute.target` systemd target.
- **Command vs chat routing**: router-1b classifies STT output as
  `cmd` (short, routed to Phase 4 Daily Assistant sub-agent) or `chat`
  (conversational, routed to supervisor). Keeps "what time is it"
  latency low.
- **Voice → agent interface**: `voice-pipecat` calls Phase 4's `POST
  /chat` (text). Cross-references Phase 4 D10. Websocket streaming is
  a v2 feature.

## Capabilities

### New Capabilities

- `voice`: Host-side voice surface — wake-word detection on NPU, STT
  pair routed by length, TTS pair routed by language, Pipecat
  orchestrator wiring it all together, persona + push-to-talk +
  listen-off controls. Talks to Phase 4 via the text `POST /chat`
  endpoint; no other agent integration.

### Modified Capabilities

- `agent-runtime` (Phase 4): No requirement changes. Phase 3 is a
  downstream consumer of the `POST /chat` interface from Phase 4 D10.
- `ai-runtime` (Phase 1): No requirement changes. Phase 3 STT, LLM,
  and TTS calls all flow through LiteLLM model aliases (`router-1b`,
  `intent-3b`, `main-70b`).

## Impact

- **`modules/`**: 6 new modules added (see tasks group 1). No existing
  module is touched.
- **`tools/aipc doctor`**: Gains a `voice` section asserting each STT
  / TTS / wake-word service is reachable on `/healthz`, the
  `aipc-voice-mute.target` exists, and the Pipecat pipeline is active.
- **`tools/aipc agent voice`**: New subcommand for persona settings,
  PTT rebind, and listen-off toggle.
- **`targets/bootc/Containerfile` + `targets/ansible/site.yml`**:
  Rendered outputs grow by 6 modules; both targets must reach the
  same end state.
- **Firstboot wizard**: Gains 2 new screens — wake-word training
  samples and persona voice (preset or 5–10s cloning sample). Owned
  jointly with Phase 7 `ops-firstboot` (Phase 3 contributes the
  screens; Phase 7 owns the wizard runner).
- **Phase 4 dependency**: `voice-pipecat` consumes Phase 4's `POST
  /chat`. Phase 4 spec already declares this interface (D10); no spec
  changes required from Phase 4.
