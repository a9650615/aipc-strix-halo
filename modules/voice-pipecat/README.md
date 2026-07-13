# voice-pipecat

## Current status: closed-loop client — push-to-talk + TTS + local intents

This module is the **user-facing turn of the always-on closed loop**
(see `docs/voice-pipeline.md` and `docs/architecture.md` § Phase 3):

```text
record → SenseVoice STT → local intent (e.g. open portal)
                       → else /chat (resident-small + mem0)
                       → Kokoro/Cosy TTS + notify-send
```

It is not the full streaming Pipecat graph yet (wake/barge-in deferred).
`aipc voice status|loop|start` and `aipc portal` are the operator surface
in `tools/aipc` — prefer those over hand-started units.

### What it does

`files/usr/bin/aipc-voice-once` — stdlib-only one-shot (also hotkey / wake):

1. Records N seconds of audio (default 5, `--seconds` or
   `$AIPC_VOICE_RECORD_SECONDS`) from the default ALSA input via
   `arecord -f S16_LE -r 16000 -c 1` — no Python audio library dependency.
2. `POST`s the WAV to SenseVoice STT (`:9001/transcribe`).
3. **Local intents** (no LLM): phrases like “打开 dashboard” / “open portal”
   call `aipc portal open` and speak/notify the result.
4. Otherwise `POST`s text to agent-orchestrator `/chat` (`:4100`) —
   default model **resident-small** (closed-loop brain).
5. Speaks via TTS router (`aipc_voice_tts.py`: Cosy → Kokoro → espeak) and
   always `notify-send` (stdout fallback).

Run it directly: `aipc-voice-once` (or `aipc-voice-once --seconds 8` for a
longer recording). `--self-test` runs offline checks only (used by
`verify.sh`).

Bind the push-to-talk shortcut from a desktop session:

```bash
aipc-voice-bind-hotkey
```

### Turn latency instrumentation (voice-telemetry)

`files/usr/lib/aipc-voice/aipc_voice_timing.py` records **one JSON line per
mic-captured turn** to `${XDG_STATE_HOME:-~/.local/state}/aipc-voice/turns.jsonl`
with the headline durations `perceived` (user end-of-speech → first audible
output), `llm_ttft`, and `tts_ttfa`, plus a small label (`path`,
`tts_backend`, `preset`). Read it with `aipc voice timings [--last N] [--json]`.

Guarantees: **best-effort** (written once at turn end, any IO error swallowed —
a logging failure never affects a turn), **no spoken content** (durations and
categorical labels only — never transcript or reply text), **bounded** (log
keeps the most recent N turns), and **disable-able** via `AIPC_VOICE_TIMING=0`.
The batch path fills `perceived`; `llm_ttft` is filled by the streaming worker
(`voice-streaming-turn`) and is null on batch. This exists to verify
`voice-streaming-turn`'s time-to-first-audio requirement; percentile /
per-scenario analytics are a deferred change.

### Siri-like partial overlay + shared UX (aipc)

**Contract owner:** `tools/aipc_lib/voice_ux.py` (import `aipc_lib.voice_ux`).

All surfaces share one status file and state vocabulary:

| Field | Meaning |
|---|---|
| `state` | `listening` / `wake` / `recording` / `thinking` / `speaking` / `done` / … |
| `detail` / `partial` | transcript or reply snippet for overlay |
| `source` / `priority` | owning widget id + preempt priority (voice default 100) |
| path | `$XDG_RUNTIME_DIR/aipc-voice-state.json` |

**Widget control API** (preferred for future assistant HUDs): Unix socket
`$XDG_RUNTIME_DIR/aipc-overlay.sock`, one JSON line per request/response.
Library: `aipc_lib.overlay_api` (`rpc` / `set_status` / `show` / `hide` / `ping`).

```bash
aipc voice status          # includes ux-state + overlay + wake
aipc voice ux              # current UX line + probes
aipc voice ux set thinking "demo"
aipc voice ptt             # same as 控制中心 (wake sock)
aipc voice overlay start   # user unit aipc-voice-overlay
aipc voice overlay ping    # control-plane health
aipc voice overlay api set thinking --detail "agent…" --source hermes
aipc voice overlay api hide
```

Python (any widget):

```python
from aipc_lib.overlay_api import set_status, hide, ping
ping()
set_status("thinking", "working…", source="my-widget", priority=50)
hide()
```

`aipc-voice-overlay` (user session, PySide6) watches the status file **and**
serves the control socket. Top-center glass card (pulsing orb + state + detail).
Esc hides the panel only — does not cancel the pipeline.

The helper reads `/etc/aipc/voice/hotkey` by default; the repo ships `F20` as
the default shortcut. KDE autostart runs the binder inside the login session,
and manual rebinding is available with `aipc-voice-bind-hotkey --shortcut F20`.
If KDE tools or `DISPLAY` are unavailable, the helper prints the commands it
would run and exits optional (`2`) instead of changing system state.

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

TTS is opportunistic via `aipc_voice_tts.py`. Routing:

- **Chinese (CJK)**: CosyVoice clone `POST :9880/tts` `{"text":...}` first
  (`AIPC_PREFER_COSYVOICE=1` default) → Kokoro `:8880/v1/audio/speech` → espeak
- **English**: Kokoro → espeak (CosyVoice only if `AIPC_TTS_FORCE_COSYVOICE=1`)
- Kokoro voice packs still respect `/etc/aipc/voice/tts-zh-voice` /
  `tts-en-voice` (and `AIPC_TTS_VOICE*`)
- Set `AIPC_VOICE_TTS=0` to force text-only output
- If all TTS backends fail, `aipc-voice-once` keeps `notify-send` / stdout

### STT interface contract

`voice-stt-sensevoice` (port 9001) landed in parallel and its real
`POST /transcribe` matches what this module assumed, confirmed by a real
round trip (see Verification below):

```
POST http://127.0.0.1:9001/transcribe
Request:  raw WAV bytes as the request body, Content-Type: audio/wav
          (16 kHz mono S16_LE — what arecord above produces)
Response: 200 {"text": "..."}
```

### Deferred (not this dispatch)

- TTS (CosyVoice 2 / Kokoro) — replaced by `notify-send` text-out per
  explicit user direction. Tasks 4.x, D5.
- NPU wake-word classifier/training pipeline — task group 2, a separate,
  more complex piece. `modules/voice-wake` doesn't exist yet.
- Full desktop hotkey registration — `aipc-voice-bind-hotkey` exists for
  runtime binding, but the broader hotkey/session integration work is
  still deferred.
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

#See `docs/voice-pipeline.md` for the staged end-to-end flow and verification tiers.

## Verification reached

- **Static**: `verify.sh` runs `ast.parse` on `aipc-voice-once` plus
  `aipc-voice-once --self-test` (offline: URL defaults, JSON response
  parsing, arg parsing).
- **Render-verified**: `tools/aipc render bootc` / `render ansible` both
  succeed and include the module now that `.disabled` is gone.
- **Hardware-verified 2026-07-06, full round trip, real content — not
  mocked at any layer**: once `voice-stt-sensevoice` landed with a real
  server (see that module), stood it up in a container for verification
  (this dev host doesn't have `python3-devel`/ROCm torch installed
  directly; see that module's README) and ran the actual
  `aipc-voice-once` CLI, unmodified, twice:
  1. `aipc-voice-once --seconds 3` recording real ambient room audio
     (silence) — the STT service transcribed it to a short garbage
     string, which still round-tripped correctly through `/chat` and
     got a coherent reply, proving the plumbing is correct even on
     nonsense input.
  2. `espeak-ng` synthesized "what time is it" to a WAV, played it
     through the real speaker with `paplay` while `aipc-voice-once
     --seconds 3` recorded at the same time — SenseVoice transcribed
     it as `"What time in it."`, which `/chat` answered

     **Correction (2026-07-06, later same day)**: this was NOT actually
     an acoustic mic test, and the claim above was wrong. Root cause,
     found when a real user tried `aipc-voice-once` and got consistent
     garbage: (1) the sound card's active PipeWire profile was
     `output:analog-stereo` (output-only, no capture Source existed at
     all), and (2) even after fixing the profile, `pactl
     get-default-source` pointed at
     `alsa_output...analog-stereo.monitor` — the **output sink's own
     monitor**, not the real mic input (`alsa_input...analog-stereo`).
     `arecord`'s "default" device silently followed that default
     source. So step 2 above was recording a digital loopback of
     `paplay`'s own output, not sound arriving through air via the
     microphone — which is exactly why it transcribed the synthesized
     phrase almost perfectly (no real room acoustics/noise at all).
     Confirmed by direct measurement: with the monitor as default
     source, `arecord` captured all-zero samples in true silence but a
     clean strong signal whenever something played through the
     speaker — a loopback signature, not a mic signature.

     **Real fix**: `pactl set-card-profile alsa_card.pci-0000_c4_00.6
     output:analog-stereo+input:analog-stereo` (expose the capture
     Source at all) and `pactl set-default-source
     alsa_input.pci-0000_c4_00.6.analog-stereo` (point recording at the
     actual mic, not the sink monitor). After both, `arecord` measured
     real non-zero, non-loopback signal (varying room-noise levels)
     with nothing playing. **Not yet confirmed**: a real human voice
     actually transcribing correctly through the fixed path — that
     needs a live person speaking, which no agent dispatch or this
     session's automated testing can do. These `pactl` settings are
     runtime PipeWire/WirePlumber state, not committed anywhere in this
     repo — they are not guaranteed to survive a reboot; if voice input
     stops working again, re-check `pactl get-default-source` and
     `pactl list cards` first before assuming a code regression.
     correctly and on-topic. `notify-send` fired for both runs.
  - This is the full v0 scope working end to end: real mic input, real
    STT, real LLM reply, real text-out. `.disabled` removed.

## Dependencies

- `llm-litellm` / agent-orchestrator's `/chat` — reused as-is, not
  touched by this change.
- `voice-stt-sensevoice` — real contract confirmed above, not touched by
  this change (that module runs as its own native systemd service).
- `alsa-utils` (provides `arecord`), `libnotify` (provides `notify-send`)
  — declared in `packages.txt`, both already present on this dev/build
  machine, verified installed via the image's package set for the target
  build.

## Bluetooth audio recovery

The user unit `aipc-bluetooth-audio-recover.service` runs once after login.
It is intentionally a no-op when the paired speaker already has a
`bluez_output` sink, or when the speaker is not connected. If BlueZ reports a
paired, connected device but PipeWire has no matching sink, it restarts the
user audio services, disconnects/reconnects the device, waits for the sink,
and sets it as default. The default target is the known LG-XT7S address
`68:52:10:35:29:44`; set `AIPC_BLUETOOTH_AUDIO_MAC` for another speaker.

The WirePlumber routing file keeps Bluetooth preferred when present and the
built-in analog output ahead of HDMI when Bluetooth is unavailable. It does
not unconditionally restart audio or delete pairings.

## Speak only (TTS, no think)

```sh
aipc-voice-say '你好，我是語音助手。'
echo '任意句子' | aipc-voice-say
aipc-voice-say --file note.txt
aipc-voice-say --kokoro 'English fallback path'
```

Uses the same router as `aipc-voice-once` (CosyVoice clone for CJK when
preferred, else Kokoro). Does **not** record, STT, or call `/chat`.

## Voice templates (apply by situation)

Named packs under `/var/lib/aipc-voice/persona/templates/<id>/` hold a
CosyVoice clone sample + manifest (system prompt, mode, TTS prefer).

```sh
aipc-voice-template list
aipc-voice-template show self-a
aipc-voice-template apply self-a          # live switch, no CosyVoice restart
aipc-voice-template current
aipc-voice-template save weekend-soft --from-current \
  --name "Weekend soft" --tags casual,soft --apply
```

`apply` copies `clone.wav`/`clone.txt` to the live persona path and writes
`persona/active.json`. CosyVoice re-reads those on the next `/tts`.

## Desktop-audio CosyVoice presets

Capture the current default output sink, transcribe it with the existing
SenseVoice service, and activate the resulting WAV + transcript as the
CosyVoice clone prompt:

```sh
aipc-voice-record-clone --desktop --seconds 10 --preset sample-name --activate
```

Presets are stored under `/var/lib/aipc-voice/persona/presets/`. Prefer
`aipc-voice-template save` for situation packs. Desktop capture uses `ffmpeg`
with the default PipeWire/Pulse sink monitor; it does not change the default
microphone source. SenseVoice supplies the transcript by default; pass
`--prompt-text 'exact words'` when its result needs correction.

## Spec

- `openspec/changes/phase-3-voice/design.md` — D9 (text in, text out to
  `/chat`). D1, D2, D5, D6, D7, D8 are explicitly out of scope here.
- Tasks 1.1, 5.1, 5.2 (this v0's slice); 1.2, 2.x, 4.x, 5.3, 5.4, 6.x,
  7.2–7.5 remain open.
