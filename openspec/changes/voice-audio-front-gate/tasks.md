# tasks: voice-audio-front-gate

## 1. Spec & skeleton

- [ ] 1.1 Write capability delta `specs/voice-audio-front/spec.md`
- [ ] 1.2 Scaffold `modules/voice-audio-front/` (README, packages, server, unit, verify, post-install)
- [ ] 1.3 Port `9010`, healthz, POST `/gate` (wav body)

## 2. Heuristic gate (v1)

- [ ] 2.1 Implement RMS / duration / noise floor → has_speech + action
- [ ] 2.2 Env knobs: enable, timeout, thr ratios
- [ ] 2.3 Unit tests with synthetic silent / speech-like PCM
- [ ] 2.4 Fail-soft client helper for wake

## 3. Wire follow-up path

- [ ] 3.1 `voice-wake`: before `submit_wav` on follow-up-originated command, call gate
- [ ] 3.2 `ignore` → `_clear_followup(hide=True)`, no once
- [ ] 3.3 Log `audio-front action= conf= ms=`

## 4. Hardware

- [ ] 4.1 Measure ambient false-open before/after
- [ ] 4.2 Real speech still answers
- [ ] 4.3 Gate down → STT still works

## 5. Model path (optional later)

- [ ] 5.1 Select local audio model; LiteLLM alias if needed
- [ ] 5.2 Same schema; hard wall; do not unpin text resident-small
