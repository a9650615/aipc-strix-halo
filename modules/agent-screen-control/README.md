# agent-screen-control

Screen control with session-gate + always-on modes (D4).

Default mode: `session-gate` — agent must request screen access per session.
Window-class blacklist prevents interaction with sensitive apps
(1Password, GNOME Keyring, etc.).

## Dependencies
- ai-rocm (VLM screenshot analysis via vlm-qwen2vl)
- llm-litellm

## Spec
openspec/changes/phase-4-agent — task 1.4
