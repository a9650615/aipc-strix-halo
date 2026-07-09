# Status — assistant-chatgpt-online (2026-07-10)

## Done

| Area | Evidence |
|---|---|
| Aggregator + unified entry | `aipc-assistant`; verify.sh |
| NPU-first / auto fallback | `runtime.yaml`; live NPU or agent |
| Multi-site engine + ChatGPT pack | `sites.yaml`, inject/voice/auth |
| Auth session | export → storage_state.json |
| First-run setup UX | `aipc-assistant setup` |
| Hardware (this host) | inject「嗨」; online turn「好」; voice start/stop/close |
| Upload/capture helpers | `aipc-chatgpt upload|capture` |
| Timeouts helper | `slots/timeouts.py` |
| OpenSpec | validate --strict |
| Commit | `d005379` + follow-up |

## Optional later

- system_audio PipeWire full graph
- project/canvas/gpt/tasks packs beyond stubs
- bootc-baked Playwright browsers
- always-on timeout daemon process
