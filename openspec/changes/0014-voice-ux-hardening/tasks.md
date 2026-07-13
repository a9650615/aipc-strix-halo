# Tasks for 0014-voice-ux-hardening

Phase A — clean files, start immediately:

- [x] 1. `aipc_voice_overlay.py`: opt out of KDE session restore (`saveStateRequest`/`commitDataRequest` → `RestartNever`) + single-instance guard on the control socket (second copy logs and exits 0). Hardware-verified 2026-07-14: ping-based guard alone races when two launchers start in the same instant (systemd unit + a leftover `.desktop.disabled` autostart entry the generator still honored) — added an `fcntl.flock`-based atomic guard as backstop.
- [x] 2. `aipc_voice_overlay.py`: active-state watchdog — `wake/recording/thinking/working/speaking/bg_task` get `_hide_at = now + AIPC_OVERLAY_ACTIVE_TIMEOUT_S` (default 120) instead of `None`; expiry falls back to hidden/listening. Hardware-verified 2026-07-14: deadline was anchored to wall-clock "now" instead of the status's own `ts`, so a restarted overlay re-reading a stale never-terminated status.json replayed a full new timeout of phantom spinner; fixed to anchor on `ts`.
- [ ] 3. `aipc_voice_overlay.py`: follow-up hold guard — `HIDE_STATES` writes within the done-hold + followup ttl window do not hide the display.
- [ ] 4. `aipc-voice-stream` / `aipc_voice_stream.py`: stream turn ends batch-style — done (hold) → followup + publish playback length for the wake follow-up window; no `_ux("done")`-then-exit.
- [ ] 5. `aipc-voice-stream`: remove the per-token `thinking` overlay ticker; visible text driven only by the per-sentence TTS callback + final done.
- [ ] 6. `screen_see.py`: stop passing `exc.read()` into visible `detail`; fixed user-facing message, truncated body to journal only.
- [ ] 7. `skill_learn.py`: `maybe_learn_async` becomes episode-log-only unless `LEARN_MODEL` is already loaded (health check, alias→model_id mapping) or `AIPC_LEARN_INLINE=1`; never cold-loads.
- [ ] 8. Self-checks/tests for 1–7 (watchdog expiry, hold guard, single-instance, stream ending sequence, screen_see message, learn gate) beside the existing voice/agent tests.
- [ ] 9. Update `modules/voice-pipecat/README.md` (lifecycle guarantees, new env knobs) and `modules/agent-orchestrator/README.md` (inline-learn policy).

Phase B — serialized after the foreign WIP and 0011 land (graphs.py / stream_chat.py shared):

- [ ] 10. `graphs.py` `_openai_chat`: gate status==200 + JSON content-type before parse; raise into the existing friendly-error path.
- [ ] 11. `stream_chat.py` `_litellm_stream`: same gate; raises become SSE `error` events (no silent empty replies).

Closing:

- [ ] 12. Static + render verification, both targets (§4, §9).
- [ ] 13. Hardware-verify on the box per how.md's scenario list; only then move modules / archive.
