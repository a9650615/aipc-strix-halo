# design: voice-audio-front-gate

## Decision

**A1: dedicated HTTP service** on localhost (like SenseVoice), not only
in-process wake logic. Reasons:

- Wake loop stays real-time; model load/lifecycle isolated.
- Can swap backend (sklearn energy features → small audio-LLM) without
  restarting wake.
- Matches existing voice service pattern (STT :9001, TTS, agent :4100).

## Pipeline placement

```text
command capture ends (or follow-up energy open)
    → POST gate with wav (or pcm path)
    → action=ignore  → clear follow-up, hide UI, no once
    → action=stt_then_route → existing STT + plan_dispatch
    → action=route → optional skip STT if target needs no body
```

## API

`POST http://127.0.0.1:9010/gate`
Content-Type: `audio/wav`
Query/env: timeout, min confidence.

Response JSON:

```json
{
  "has_speech": true,
  "action": "ignore" | "route" | "stt_then_route",
  "target": "respond" | "daily_assistant" | "hermes" | "screen_see" | "job_status" | null,
  "mode": "short" | "long" | null,
  "confidence": 0.0,
  "latency_ms": 12,
  "source": "heuristic" | "model"
}
```

## v1 backend (ship first, hardware-prove)

**Heuristic audio gate** (no heavy multimodal weights):

- RMS / speech-band energy vs noise floor
- Duration + zero-crossing / simple spectral flatness (stdlib + numpy if
  already in venv)
- Maps to `has_speech` + `action=ignore|stt_then_route`
- `route` with target reserved for later model

This is **not** a fake multimodal claim — it is a real front gate that
does not require STT text. Swap `source=model` when a small audio model
is selected and measured.

## v2 backend (optional)

- Local audio-LLM or classifier via LiteLLM alias `audio-front`
- Same JSON schema; hard wall `AIPC_AUDIO_FRONT_TIMEOUT_MS`
- On timeout: treat as `stt_then_route`

## Resources

- Default: **CPU**, always-on small process, no NPU pin contest with
  `gemma4-it-e4b-FLM`.
- Env: `AIPC_AUDIO_FRONT_URL`, `AIPC_AUDIO_FRONT_TIMEOUT_MS`,
  `AIPC_AUDIO_FRONT=1|0` (off = skip gate, pure STT).

## Failure modes

| Failure | Behavior |
|---------|----------|
| Gate down | STT path (fail-soft) |
| Gate timeout | STT path |
| Gate ignore | No once; dismiss UI |
| Gate route without body | Only for targets that do not need utterance text (rare); else stt_then_route |

## Verification

- Static: unit tests for heuristic ignore/speech on synthetic wavs.
- Render: module in bootc + ansible.
- Hardware: false-open rate on ambient follow-up vs baseline; real speech
  still reaches agent.
