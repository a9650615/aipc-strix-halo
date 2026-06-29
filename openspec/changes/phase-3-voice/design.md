## Context

The AI PC is voice-primary in its non-coding use cases. The microphone
is always on (low-power NPU listening for the wake word); STT, LLM, and
TTS engage only after wake or after a push-to-talk press. The user
records their own wake word ("小華" / "Jarvis" / whatever) at firstboot,
plus a 5–10 s sample that CosyVoice 2 zero-shot-clones for the
assistant's reply voice — the assistant sounds like the user wants it
to sound, not like a stock vendor voice.

Pipecat is the orchestrator. The pipeline graph (wake → STT → router →
`/chat` → TTS) is config, not code; switching the architecture from
path A (STT + LLM + TTS, the default) to path B (multimodal-first,
Qwen2.5-Omni) is a Pipecat pipeline swap, not a rewrite. Path B is
deferred to v2 because Qwen2.5-Omni's viability on gfx1151 needs a
hardware benchmark (Open Question Q1).

The voice surface is downstream of Phase 4: `voice-pipecat` calls
`POST /chat` with text and gets text back, then synthesises. No
websocket streaming, no shared agent state — text in, text out. This
keeps the agent runtime free of audio concerns and keeps the voice
pipeline swappable.

## Goals / Non-Goals

**Goals:**

- Boot the AI PC, say the user-trained wake word, get a spoken reply
  through a personalised cloned voice in under ~2 s end-to-end for
  short commands.
- Always-on listening costs ≤ ~100 mW (NPU only); STT / LLM / TTS
  never run idle.
- Listen-off is bulletproof: any of screen-lock, voice mute, GNOME DND
  pauses wake-word inference; status visible to the user.
- Short commands ("what time is it", "open notes") hit the Daily
  Assistant sub-agent directly via router-1b, bypassing the supervisor
  graph latency.
- Pipeline shape is config-driven; swapping to multimodal-first (path
  B) when Qwen2.5-Omni proves viable is a `voice-pipecat` config edit.

**Non-Goals:**

- Voice barge-in (user interrupts TTS mid-sentence). v2 feature; needs
  Pipecat interrupt-handling work.
- Multi-user voice ID (different replies per recognised speaker). v2.
- Cloud STT/TTS fallback. Voice stays local; if the local stack is
  down, the assistant is silent — a deliberate privacy choice.
- Embedded TTS in the agent runtime. Voice is one of N possible
  surfaces in front of `/chat`; the agent stays text-only.
- Wake-word training UI on the GNOME desktop. The TUI firstboot wizard
  (Phase 7) hosts the screen; a GUI version is v2.

## Decisions

**D1 — Architecture: STT + LLM + TTS separate (path A) by default; multimodal-first (path B) is opt-in v2**

*Chosen:* Path A ships as the default Pipecat pipeline. Path B
(Qwen2.5-Omni native speech-in/speech-out) is wired as a Pipecat
pipeline variant the user can switch to via `aipc agent voice
settings`, but only once Q1 (hardware viability on gfx1151) is
answered green.

*Alternatives:*
- Path B only: lower latency in theory, single model, but no proof it
  meets latency targets on gfx1151 yet; locks the user out of
  CosyVoice voice cloning.
- Path C (router-1b classifies short/long, splits to different
  pipelines): best UX but doubles maintenance and adds a routing edge
  case (mis-classified utterance hits the wrong pipeline).

*Why chosen:* Path A is proven, each component is small and replaceable,
and Pipecat's pipeline abstraction means moving to B later is a config
change. CosyVoice 2 cloning is a user-visible win we can ship today;
path B doesn't offer it.

**D2 — Custom wake word trained on NPU at firstboot; always-on at low power**

*Chosen:* Firstboot wizard records 3–5 samples of the user's chosen
wake word; a small ONNX classifier (openWakeWord training pipeline) is
fitted on-device and saved to
`/var/lib/aipc-voice/wake/<phrase>.onnx`. `voice-wake` loads the model
onto the NPU and runs always-on inference at low power
(~100 mW target).

*Alternatives:*
- Porcupine pretrained models: easier to ship, but not personalisable
  and has no native Chinese-name support like "小華".
- PTT-only (no wake word): kills the "Hey Jarvis" UX the AI PC is built
  around.
- Train wake word on cloud, deploy locally: violates local-only stance.

*Why chosen:* User-explicit personalisation; NPU is the right home for
always-on (the iGPU would draw orders of magnitude more). Training
takes seconds for a binary classifier on 3–5 samples; the wizard
shows progress in real time.

**D3 — Persona: no default name; firstboot wizard sets name, voice preset, and optional cloning sample**

*Chosen:* The image ships without an assistant name. Firstboot wizard
screen 1 (Phase 7 wizard, voice contribution) prompts: (a) name, (b)
voice — choose preset (`female-zh`, `neutral-zh`, `female-en`) or
record 5–10 s for CosyVoice 2 zero-shot cloning. The chosen name
becomes the wake word's training label.

*Alternatives:*
- Hard-coded default ("Aipc", "Jarvis"): saves a wizard step, but the
  point of training a custom wake word is personalisation; pairing it
  with a fixed name is incoherent.
- Voice preset only, no cloning: simpler, but loses the headline
  feature of CosyVoice 2.

*Why chosen:* Aligns with D2 — if the user is training their own wake
word, they own the persona around it. Presets keep the "I don't care,
just pick one" path fast.

**D4 — STT: both SenseVoice and Paraformer ship; router-1b picks by length**

*Chosen:* `voice-stt-sensevoice` and `voice-stt-paraformer` both run
as systemd services. Pipecat sends the audio to a "router" node first
(short Lemonade pass that emits a length classification), which then
dispatches to SenseVoice (<10 s, faster) or Paraformer (longer,
streaming).

*Alternatives:*
- SenseVoice only: long dictation suffers (no streaming, latency
  spikes).
- Paraformer only: short-command latency is worse than SenseVoice.
- Whisper: heavier, weaker on Chinese.

*Why chosen:* Both models are small enough to run side-by-side; the
length classifier is cheap; the user gets best-fit STT per utterance
with no manual switching.

**D5 — TTS: CosyVoice 2 primary (zh + cloning); Kokoro fallback (en)**

*Chosen:* `voice-tts-cosyvoice` and `voice-tts-kokoro` both run.
router-1b decides per-utterance language (already classified during
STT routing) and Pipecat dispatches. CosyVoice 2 uses the firstboot
cloning sample when present; otherwise the chosen preset.

*Alternatives:*
- CosyVoice only: English suffers (audible accent).
- Kokoro only: no Chinese cloning, kills D3's headline feature.
- Single multilingual TTS (XTTS-v2): worse quality on both languages
  than the language-specific pair.

*Why chosen:* Best of both, per-utterance routing is free (language
already known from STT step).

**D6 — Push-to-talk: Super+Space default, configurable**

*Chosen:* `voice-pipecat` installs a GNOME custom keybinding for
`Super+Space` mapped to `aipc agent voice force-wake`. Pressing the
hotkey emits a synthetic wake event to Pipecat that bypasses the
wake-word classifier (treats the next ~10 s as captured audio).

*Alternatives:*
- No PTT: voice-only path breaks in noisy environments or when the
  wake-word classifier needs retraining.
- User picks at firstboot: slows down onboarding for a setting most
  users won't change.

*Why chosen:* `Super+Space` is mainstream (Spotlight muscle memory)
and not bound by GNOME's defaults. Rebind via `aipc agent voice
settings` for users who need it.

**D7 — Listen-off: three independent triggers, all gate the same systemd target**

*Chosen:* Three triggers each toggle `aipc-voice-mute.target`:
- GNOME screen lock (via DBus `org.gnome.ScreenSaver.ActiveChanged`).
- Voice command (`mute`, `DND` recognised words → Daily Assistant
  routes to the mute action).
- GNOME Do-Not-Disturb toggle (via the same DBus surface).

Any one ON → target active → `voice-wake.service`'s
`BindsTo=!aipc-voice-mute.target` pauses NPU inference. A tray
indicator (Phase 7 doctor / desktop integration) shows current state.

*Alternatives:*
- Tray-icon-only: requires GUI; breaks on gamescope session.
- Single trigger: less control; users with security concerns want
  multiple paths to "off".
- Hard kill (stop the service): re-enabling has latency; pause via
  target is instant.

*Why chosen:* Redundant safety, all three converge on one mechanism
(`aipc-voice-mute.target`), nothing to special-case.

**D8 — Command vs chat: router-1b binary classifier post-STT**

*Chosen:* After STT, Pipecat sends the transcribed text to a
`router-1b` LiteLLM call with a short classifier prompt. Output is
`cmd` or `chat`. `cmd` routes to Phase 4 Daily Assistant directly
(short HTTP call); `chat` goes to the Phase 4 supervisor via `POST
/chat`.

*Alternatives:*
- All-to-supervisor: simpler, but "what time is it" pays the
  supervisor-graph latency.
- Separate wake words per intent: hostile UX.
- Heuristic length/keyword: fragile across languages.

*Why chosen:* router-1b is already a model alias the Phase 1 LiteLLM
gateway ships; a 1B model classifies in tens of ms; the latency
savings on short commands are visible.

**D9 — Voice → agent interface: HTTP POST `/chat` (text) per Phase 4 D10**

*Chosen:* `voice-pipecat` sends transcribed text to
`http://127.0.0.1:8088/chat` and receives text in reply, then
synthesises via TTS. No streaming, no shared state.

*Alternatives:*
- Websocket streaming: smoother first-token latency, but adds a stateful
  surface to both sides. v2.
- Direct LangGraph SDK call: tighter coupling between voice and agent
  runtime; Pipecat would import LangGraph. Loses the "voice is one
  surface among many" property.

*Why chosen:* Matches Phase 4 D10 ("text in, text out") exactly.
Websocket can be added in v2 without breaking the HTTP path.

## Risks / Trade-offs

- **Wake-word false-positive rate**: a small classifier trained on 3–5
  samples can over-trigger in noisy environments. **Mitigation**:
  expose threshold in `aipc agent voice settings`; default to a
  conservative value and let the user tighten / loosen. Q2 leaves the
  number unspecified until hardware testing.
- **Always-on microphone privacy posture**: even with NPU-local
  inference, the mic is hot. **Mitigation**: D7's three listen-off
  triggers + a hardware-level reminder in firstboot ("you can
  always-off by hitting GNOME DND or saying 'mute'").
- **CosyVoice 2 cloning quality from 5–10 s**: short samples can sound
  uncanny. **Mitigation**: wizard offers re-record and "use preset
  instead" escape hatches; presets are the safe default.
- **Path B not viable on gfx1151 in this release**: Q1 is open;
  multimodal-first remains a pipeline switch, not a shipping default.
  **Mitigation**: ship path A; path B becomes default in a follow-up
  change once benchmarked.
- **PTT collision with other Super+Space bindings**: some users bind
  Super+Space to language switcher. **Mitigation**: rebind path in
  `aipc agent voice settings`; document the collision in `voice-pipecat`
  README.
- **router-1b mis-classification (`cmd` vs `chat`)**: an
  conversational query mis-routed to Daily Assistant truncates the
  response. **Mitigation**: Daily Assistant graph escalates to
  supervisor when its tools don't match the intent; users see a
  slight latency penalty on a small fraction of utterances, not a
  wrong answer.

## Migration Plan

No prior voice surface exists on this image. Phase 3 is net-new. The
only ordering concern is Phase 4: `voice-pipecat` needs `POST /chat`
to be live to do anything useful, so Phase 3 hardware verification
gates on Phase 4 being deployed first. Module install order in the
bootc Containerfile is irrelevant (no quadlet cross-deps); systemd
After= edges in `voice-pipecat.service` handle the runtime ordering.

## Open Questions

- **Q1 — Qwen2.5-Omni viability on gfx1151**: path B unlocks only when
  end-to-end latency is provably ≤ path A on the AI PC's hardware.
  Needs a benchmark in a `:rolling` build before changing the default.
- **Q2 — Wake-word false-positive threshold**: spec deliberately does
  not fix a number; needs hardware-side user testing. The setting is
  exposed and tuneable; the default may shift after deployment.
- **Q3 — Voice barge-in**: user interrupting TTS mid-sentence is a
  common feature in commercial assistants. Deferred to v2 because it
  requires Pipecat interrupt support and a duplex audio path.
