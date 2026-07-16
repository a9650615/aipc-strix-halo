# voice-wake — honest status (2026-07-17)

## What is actually done (control-plane safety)

| Item | Status | Evidence |
|------|--------|----------|
| Particle STT (`我。`) does not clear-arm | **Done** | `phrase_hit` / `classify_wake_text`; tests |
| Fuzzy promote default off | **Done** | `wake-policy.env` + code default |
| Escalating miss backoff (no 1.5s STT thrash) | **Done** | `miss_backoff_seconds`; tests |
| Intentional junk → 沒聽清 once → `mode=listen` | **Done** | `junk_capture_action` + `next_mode_after_empty_capture` |
| Single policy file authority | **Done** | `/etc/aipc/voice/wake-policy.env` preload |
| `--print-policy` dump | **Done** | CLI flag |
| Unit thin + `/run/aipc` as root | **Done** | `ExecStartPre=+` |
| Live path `/var/lib` matches repo | **Done** | unit ExecStart |
| Always-on left disabled after freezes | **Intentional** | operator safety |
| `aipc doctor` wake checks | **Done** | `check_voice_wake` |

## What is NOT done (do not claim)

| Item | Status | Notes |
|------|--------|-------|
| Split 2.8k god-object into session/capture modules | **Not done** | still one `aipc_voice_wake.py` |
| Explicit state machine enum (IDLE/ARMED/…) | **Not done** | design P1 |
| FOLLOWUP_ARMED probe UX (no show on noise) fully | **Partial** | `FOLLOWUP_DIRECT=0` default; no full probe state |
| Ostree `/usr/lib` image parity | **Not done** | `/usr` is **stale** (no thrash/anti-ghost helpers) until bootc rebuild |
| OpenSpec `0019-voice-session-runtime` change | **Not done** | design doc only |
| Hardware-verified always-on soak | **Not done** | always-on off by design |
| Safe re-enable of always-on | **Not done** | needs thrash + GPU soak under load |
| YAML config schema (design) | **Deferred** | `.env` used instead |

## How to verify without enabling always-on

```bash
python3 /var/lib/aipc-voice/lib/aipc_voice_wake.py --self-test
python3 /var/lib/aipc-voice/lib/aipc_voice_wake.py --print-policy
cd /var/home/birdyo/aipc-strix-halo && python3 -m pytest tools/tests/test_voice_wake_tier.py tools/tests/test_voice_wake_config.py tools/tests/test_doctor_voice.py -q
# doctor (if installed)
aipc doctor   # should list voice-wake-policy / voice-wake-code / voice-wake-unit
```

## Re-enable always-on (only after you accept risk)

```bash
sudo rm -f /run/aipc/voice-mute
sudo systemctl enable --now aipc-voice-wake.service
journalctl -u aipc-voice-wake -f
# Fail if energy→STT more often than ~once per miss_backoff window under silence
```
