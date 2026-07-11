# proposal: voice-audio-front-gate

## Why

The closed-loop voice path still opens “接话 / command” on energy and STT
text. Ambient noise produces junk transcripts (`我。`) or empty turns; the
user wants **meaningful speech detection and coarse intent without first
depending on SenseVoice text**. False opens and dead stacks are separate
P0 ops issues; this change adds a **front audio gate** so ignore/route can
run on the waveform.

## What

- New capability: **audio front gate** — short WAV → structured JSON
  (`ignore` | `route` | `stt_then_route` + optional target/mode).
- Wire **follow-up / post-capture** first (highest ROI for false 接话).
- Hard wall (default ≤500ms class, env-tunable); **fail-soft to STT**.
- Offline local weights only for default; cloud opt-in later only.
- Does **not** replace STT for task body (提示词+任务, code, URLs).
- Does **not** unload large models; must not steal NPU pin from text
  `resident-small` without hardware proof.

## Out of scope

- End-to-end audio chat (no text ever).
- Replacing wake-word phrase STT in phase 1.
- Cloud multimodal as default.

## Modules

- New: `modules/voice-audio-front/` (HTTP gate service + client helpers).
- Touch: `voice-wake` (call gate before once on follow-up path).
- Optional later: `aipc-voice-once`, LiteLLM alias if a chat-style audio
  model is used.
