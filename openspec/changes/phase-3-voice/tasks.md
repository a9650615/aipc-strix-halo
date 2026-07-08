## 1. Module Scaffolding (6 modules)

- [ ] 1.1 `voice-pipecat`: **partially done, reduced v0 scope, not
  fully checked off.** Per explicit user direction (text-out is fine,
  no TTS yet), a hardware-verified v0 landed instead of this task's
  full ask: a manually-invoked `aipc-voice-once` CLI (record -> STT ->
  `/chat` -> `notify-send`), plain stdlib not `pipecat-ai`, no GNOME
  keybinding registration, no `aipc-voice-mute.target` wiring. See
  `modules/voice-pipecat/README.md` for the full scope decision and
  verification. Remaining for this task: `pipecat-ai`/full pipeline
  graph, keybinding registration, mute-target wiring.
- [ ] 1.2 `voice-wake`: create `modules/voice-wake/` with README,
  packages.txt (openwakeword, onnxruntime), files/ for the wake
  service systemd unit with `BindsTo=!aipc-voice-mute.target`,
  post-install.sh (no-op until firstboot writes the model),
  verify.sh (unit present, NPU device node accessible).
- [x] 1.3 `voice-stt-sensevoice`: create
  `modules/voice-stt-sensevoice/` with README, files/ for a native
  systemd service running SenseVoice-Small (port 9001; no quadlet —
  the originally-scaffolded container image never existed), verify.sh
  (`/healthz` returns 200).
- [ ] 1.4 `voice-stt-paraformer`: create
  `modules/voice-stt-paraformer/` with README, files/ for the
  quadlet running Paraformer-zh-streaming (port 8102), verify.sh
  (`/healthz` returns 200).
- [ ] 1.5 `voice-tts-cosyvoice`: create `modules/voice-tts-cosyvoice/`
  with README, files/ for the quadlet running CosyVoice 2 (port
  8111) with a mount point at `/var/lib/aipc-voice/persona/` for the
  cloning sample, verify.sh (`/healthz` returns 200, mount writable).
- [ ] 1.6 `voice-tts-kokoro`: create `modules/voice-tts-kokoro/` with
  README, files/ for the quadlet running Kokoro / Piper (port
  8112), verify.sh (`/healthz` returns 200).

## 2. Wake-Word Training Pipeline

- [ ] 2.1 Wake-word trainer script (`voice-wake/files/usr/libexec/aipc-voice-train-wake`):
  takes 3–5 WAV samples + phrase label, fits openWakeWord
  classifier, writes `/var/lib/aipc-voice/wake/<phrase>.onnx`.
  Runnable from the firstboot wizard.
- [ ] 2.2 Wake-word loader: `voice-wake.service` reads the configured
  phrase from `/etc/aipc/voice/persona.yaml` and loads
  `/var/lib/aipc-voice/wake/<phrase>.onnx`. Restarts on file change
  (systemd `Restart=` + `PathExists=` via a watcher).
- [ ] 2.3 Threshold setting in `aipc agent voice settings` (Q2 — value
  exposed, no default change without hardware data).
- [ ] 2.4 Document network-isolation expectation for training (no
  outbound connections from the trainer script).

## 3. STT Services + Router

- [x] 3.1 SenseVoice running via native systemd (no quadlet, no
  Lemonade — see `voice-stt-sensevoice`'s README). CPU fallback per
  this task's own escape clause: `cuda:0` segfaults on this
  torch/ROCm/gfx1151 combination (hardware-verified), CPU is fast
  enough (rtf 0.092) to be the real default, not a stopgap.
- [ ] 3.2 Paraformer-zh-streaming quadlet, streaming-mode
  configuration.
- [ ] 3.3 Pipecat router step: `router-1b` classifier prompt that
  emits `short` | `long` based on audio metadata (duration), then
  dispatches.

## 4. TTS Services + Language Router

- [ ] 4.1 CosyVoice 2 quadlet with reference-sample mount,
  zero-shot-clone path enabled when sample present.
- [ ] 4.2 Kokoro / Piper quadlet (English).
- [ ] 4.3 Pipecat language-router step: dispatch by language tag
  already produced during STT routing.

## 5. Pipecat Orchestrator + /chat Client

- [ ] 5.1 **Not done at full scope.** v0 (`aipc-voice-once`) calls STT
  and `/chat` directly but has no wake, no TTS, no cmd/chat router, no
  path-B — see `modules/voice-pipecat/README.md`. `files/etc/aipc/pipecat/pipeline.yaml`
  (the path-A config) exists from the original scaffold but is not
  read by v0.
- [ ] 5.2 **Partially done.** Hardware-verified `/chat` client exists
  (`chat()` in `aipc-voice-once`) with a configurable URL
  (`$AIPC_VOICE_CHAT_URL`, defaults to agent-orchestrator's real
  `env/endpoint`-declared port) and a request timeout, but no retry
  logic per Phase 4 D10.
- [ ] 5.3 `cmd` routing wires the Daily Assistant short-command
  endpoint (Phase 4) directly, not through the supervisor.
- [ ] 5.4 No LangGraph import; assert via grep in `verify.sh`.

## 6. Firstboot Wizard Hooks (joint with Phase 7)

- [ ] 6.1 Persona screen contribution: name + voice preset / clone
  sample capture. Writes `/etc/aipc/voice/persona.yaml` and
  `/var/lib/aipc-voice/persona/clone.wav`.
- [ ] 6.2 Wake-word screen contribution: 3–5 sample recording UI
  (TUI), invokes `aipc-voice-train-wake`, surfaces progress.
- [ ] 6.3 Hand-off: both screens are owned in Phase 3 but rendered by
  the Phase 7 `ops-firstboot` wizard runner.

## 7. Listen-Off Triggers + systemd Target

- [x] 7.1 Runtime push-to-talk binding helper exists as `aipc-voice-bind-hotkey`; static-verified only. Full desktop hotkey behavior remains hardware/manual-session verification.
- [ ] 7.2 Screen-lock listener: small DBus-monitor service that
  starts/stops `aipc-voice-mute.target` on
  `org.gnome.ScreenSaver.ActiveChanged`.
- [ ] 7.3 GNOME DND listener: same shape on the DND DBus signal.
- [ ] 7.4 Voice mute action: Daily Assistant `mute` tool toggles the
  target via DBus to `systemd1`.
- [ ] 7.5 `voice-wake.service` declares `BindsTo=!aipc-voice-mute.target`.

## 8. Doctor Checks

- [x] 8.1 `aipc doctor` includes static voice checks for `aipc-voice-once`, SenseVoice unit install/activity, and notifier fallback. Full Pipecat/STT/TTS/wake health checks remain open for the full Phase 3 runtime path.
- [x] 8.2 Desktop/microphone/runtime readiness is reported as optional/warn instead of render-time failure. Persona and wake-word artifact checks remain open until firstboot/wake tasks land.

## 9. Documentation

- [ ] 9.1 Per-module README for each of the 6 modules: purpose,
  packages, files, dependencies, verify behaviour, firstboot user
  actions where applicable.
- [ ] 9.2 `docs/voice-pipeline.md`: end-to-end diagram + path-A
  default + path-B opt-in toggle instructions.
- [ ] 9.3 Confirm `docs/architecture.md §7` Phase 3 row matches the
  6-module list shipped here (no count change to the §7 header
  total).

## 10. Local Build Verification

- [ ] 10.1 Run `tools/aipc render bootc`; confirm Containerfile
  includes all 6 voice modules.
- [ ] 10.2 Run `tools/aipc render ansible --check`; confirm it lints
  clean.
- [ ] 10.3 Run each module's `verify.sh` in a privileged container;
  all non-optional modules exit 0.

## 11. AI PC Hardware Verification

- [ ] 11.1 Deploy `:rolling` tag to the AI PC via `bootc switch`.
- [ ] 11.2 Run firstboot wizard; complete persona + wake-word
  screens. Confirm `/etc/aipc/voice/persona.yaml` and
  `/var/lib/aipc-voice/wake/<phrase>.onnx` exist.
- [ ] 11.3 Say the wake word + a short command; confirm Daily
  Assistant handles it (router classified `cmd`).
- [ ] 11.4 Say the wake word + a multi-sentence query; confirm
  supervisor handles it via `POST /chat`.
- [ ] 11.5 Lock screen; confirm `aipc-voice-mute.target` activates
  and wake-word inference pauses. Unlock; confirm resume.
- [ ] 11.6 Smoke-test PTT: press `Super+Space` and speak; confirm
  Pipecat trace shows force-wake event (no classifier).
- [ ] 11.7 (Q1 hardware bench) Measure Qwen2.5-Omni latency on
  gfx1151 against path-A baseline; log result for the path-B
  follow-up change.

## 12. Archive Change

- [ ] 12.1 Run `npx -y @fission-ai/openspec validate phase-3-voice
  --strict` — must print `Change 'phase-3-voice' is valid`.
- [ ] 12.2 Run `npx -y @fission-ai/openspec archive phase-3-voice` to
  merge the spec into `openspec/specs/voice/spec.md` and close the
  change.
