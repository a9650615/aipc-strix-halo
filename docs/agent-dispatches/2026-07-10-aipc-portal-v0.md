# Task: aipc portal v0 (localhost management homepage)

**Role:** 副官  
**Orchestrator:** grok-4.5 session (voice baseline + aipc voice CLI)  
**Agent-Run:** aipc-portal-v0-2026-07-10  
**Spec-Task:** aipc-portal-v0 (create OpenSpec change under this name)

## Why

Operators are tired of hammering CLI for status of always-on baseline
(resident-small + SenseVoice + Kokoro + mem0) and peer services. There is
already a design at:

- `docs/superpowers/specs/2026-07-08-aipc-mem0-dashboard-portal-design.md`
- `docs/superpowers/plans/2026-07-08-aipc-mem0-dashboard-portal.md`

**This dispatch is portal-only v0.** Do **not** rewrite `memory-mem0` to the
official Mem0 self-hosted dashboard (that spike stays deferred). Ship a
localhost entry page + `aipc portal` CLI so the user can open a browser
instead of retyping `aipc voice status` / `aipc status`.

## In scope (do these)

1. **OpenSpec change** `openspec/changes/aipc-portal-v0/` with proposal,
   design (thin), tasks.md, and delta spec `specs/aipc-portal/spec.md`.
   Scope: entry portal + metadata contract + CLI. Explicit non-goal:
   official Mem0 UI swap.

2. **Module** `modules/system-aipc-portal/` (enabled, not `.disabled`):
   - stdlib-only Python HTTP server on `127.0.0.1:7080` (see plan)
   - reads `/etc/aipc/portal/services/*.yaml` (+ graceful empty dir)
   - HTML page: auto-refresh ~5s, cards with title, module, unit status,
     health status, endpoint, UI link
   - systemd unit `aipc-portal.service` (Type=simple, Restart=on-failure)
   - `post-install.sh` build-time only (chmod, install files) — **no**
     `systemctl --now`, no curl health loops
   - `verify.sh` static always; live HTTP only if unit active
   - self-card `files/etc/aipc/portal/services/aipc-portal.yaml`

3. **Portal metadata** (ship under each module's `files/etc/aipc/portal/services/`):
   - `memory-mem0` → mem0.yaml (health :7000/healthz)
   - `voice-stt-sensevoice` → sensevoice.yaml (:9001)
   - `voice-tts-kokoro` → kokoro.yaml (:8880) — note unit may be quadlet
     `aipc-kokoro.service`; also document container name
   - `llm-litellm` → litellm.yaml if health path known, else endpoint-only
   - `llm-lemonade` → lemonade.yaml (`/api/v0/health`)
   - optional: `voice-pipecat` card pointing at helpers / docs URL null

4. **CLI** in `tools/aipc_lib/`:
   - `portal.py` — load cards, probe unit+health, format text status,
     open browser helper (`xdg-open` / `webbrowser`)
   - `aipc portal` → print URL + one-line card summary (reuse probes)
   - `aipc portal open` → start browser to `http://127.0.0.1:7080/`
   - `aipc portal serve` (optional for dev) — run server in foreground
     from installed package path OR tools fallback for live hotfix hosts

5. **Live-host fallback (important on this AI PC):** ostree may not have
   the module installed yet. Allow `aipc portal open` / `serve` to run the
   server from `tools/` or `modules/system-aipc-portal/files/usr/lib/...`
   so the user gets value before next bootc switch. Prefer installed unit
   when present.

6. **Tests** `tools/tests/test_portal.py`:
   - parse YAML cards (PyYAML if already a dep; else minimal subset —
     prefer existing repo patterns)
   - empty registry → still renders
   - CLI `portal` help / status dry path with monkeypatched probes
   - no network required in unit tests

7. **Docs**
   - short section in `docs/voice-pipeline.md` under aipc CLI pointing to
     `aipc portal open`
   - module README
   - append `docs/agent-log.md` row

## Out of scope (do not)

- Official Mem0 dashboard container / rewrite of aipc-mem0 API
- Auth / remote bind / reverse proxy
- Custom complex SPA (stdlib HTML is enough; keep CSS small)
- Changing model_presets / voice_ops behavior beyond reading them for
  optional "baseline" summary row
- Enabling `.disabled` CosyVoice
- Force-push, secrets, or new paid deps

## Conventions (must)

- CLAUDE.md §3 module discipline, §4 bootc+ansible render parity
- §5 no secrets; §8 no comments unless non-obvious; build-time/runtime split
- §11 commit trailers:
  ```
  Co-authored-by: <your-model-id> <noreply@…>
  Agent-Role: 副官
  Agent-Run: aipc-portal-v0-2026-07-10
  Spec-Task: aipc-portal-v0#<task>
  Agent-Orchestrator: grok-4.5
  ```
- Verification: name tier. Expect **static + render-verified**. Hardware
  `systemctl start aipc-portal` only if you can; otherwise document live
  fallback via `aipc portal serve`.

## Verify commands

```bash
# static
PYTHONPATH=tools python3 -m pytest tools/tests/test_portal.py tools/tests/test_voice_ops.py -q
# if openspec CLI available:
# npx -y @fission-ai/openspec validate aipc-portal-v0 --strict

# render
PYTHONPATH=tools python3 -m aipc_lib.cli render bootc --image-ref test --build-date 2026-07-10
PYTHONPATH=tools python3 -m aipc_lib.cli render ansible --check   # or whatever flag site uses

# smoke (optional live)
PYTHONPATH=tools python3 -m aipc_lib.cli portal
PYTHONPATH=tools python3 -m aipc_lib.cli portal serve &  # then curl 127.0.0.1:7080
```

## Report back

1. Files touched  
2. What was skipped / why  
3. Verification tier actually reached  
4. Commit SHAs if committed  
5. How user opens the UI today on this host without reboot
