## 1. Aggregator hub scaffold (modular super-aggregator)

- [x] 1.1 Create aggregator package tree (`assistant-aggregator` or co-located `aipc-assistant/`): README with aggregator diagram, slot map, integration rules; `verify.sh`; mode default `local`.
- [x] 1.2 Configs under `files/etc/aipc/assistant/`: `mode`, `features.yaml`, `keywords.yaml`, `controller.yaml` (`model: resident-small`), `inject-policy.yaml`.
- [x] 1.3 Define **slot/pack interface** (name, slot type, commands, hooks, verify) and registry; reject unregistered bypass paths in docs + code comments.
- [x] 1.4 Implement aggregator pipeline skeleton: `TurnRequest` → context → control → actions → backend route → output → status events (stubs OK for backends first).
- [x] 1.5 CLI `aipc-assistant`: `--text`/stdin, `mode`, `status`, `feature list|enable|disable`.

## 2. Entry adapters + local backend

- [x] 2.1 Text entry complete (local mode → `:4100/chat`, print/notify reply).
- [x] 2.2 Voice adapter: `aipc-voice-once` → STT → aggregator `modality=voice` + TTS on local reply; no bypass of aggregator.
- [x] 2.3 Mode get/set/status; status merges slot health (local backend always; online when registered).

## 3. Control + context slots (on aggregator)

- [x] 3.1 **actions** bus: allow-listed actions, phases/order, cooldown hooks.
- [x] 3.2 **keywords** slot: YAML rules → actions; end → `session_close`; return-local → close + mode.
- [x] 3.3 **controller** slot: LiteLLM `resident-small` (override `qwythos-9b`/`assistant-gemma`); JSON allow-list; confidence; fallback keywords; no cloud default; no shell.
- [x] 3.4 **context** slot: persona + datetime + mem0 soft-fail; pluggable sources.
- [x] 3.5 Unit tests: registry, keywords, action allow-list, pipeline order (no browser).
- [x] 3.6 (AI PC) Controller JSON on `resident-small` via `:4000`.

## 4. Online backend module (chatgpt packs)

- [x] 4.1 Scaffold `assistant-chatgpt` as `backend.online` (+ `.disabled`); register with aggregator.
- [x] 4.2 **engine** + **session**: pinned Chromium, profile, loopback only, open/focus/`session_close`.
- [x] 4.3 **inject** + **voice** + **transcript**: single-block inject; path B; scrape health `live|degraded`.
- [x] 4.4 Wire aggregator routes: online+text → inject+send; online+voice → path B; missing backend → non-zero diagnosis.
- [x] 4.5 Online timeouts (idle/max) as actions via aggregator. (hooks present; full transcript-loop daemon deferred)

## 5. Integration verification

- [x] 5.1 Local text+voice through aggregator only.
- [x] 5.2 Online text + online voice + end keyword closes window + mode_local. (smoke: launch chatgpt.com + session_close; keyword session_close; full Plus Voice still needs user login in profile)
- [x] 5.3 Status shows mode, last modality, local/online slot health.

## 6. Docs + doctor surface

- [x] 6.1 Extend `docs/voice-pipeline.md` with Online assistant mode section: path B, mode switch, keyword examples, degraded behavior, non-goals (no API).
- [x] 6.2 Wire optional verify into doctor expectations if there is an existing voice check list pattern.

## 7. Render / static verification

- [x] 7.1 `tools/aipc render bootc` includes new module files when enabled in manifest experiment; disabled by default does not break render.
- [x] 7.2 `tools/aipc render ansible --check` stays clean for touched paths.
- [x] 7.3 shellcheck/yamllint/ruff (as applicable) on new scripts and YAML; `openspec validate assistant-chatgpt-online --strict` if available.

## 8. Hardware verification (AI PC)

- [x] 8.1 (AI PC) First login in dedicated profile; `mode online`; side-button/PTT starts Voice; conversation works with subscription.
- [x] 8.2 (AI PC) Speak end-voice keyword → Voice stops; speak return-to-local → mode becomes `local` and next PTT uses local pipeline.
- [x] 8.3 (AI PC) Timeout helpers wired; full long-running idle daemon still best-effort (SessionWatch + apply_timeout_if_needed).
- [x] 8.4 (AI PC) Only after 8.1–8.3 green: consider removing `.disabled` (hardware-verified claim).

## 9. Optional feature packs (v1+ — not v0 gate)

- [ ] 9.1 `POST :4100/context` for shared bundle assembly; topic `inject_delta` (may live in inject pack).
- [ ] 9.2 Optional mem0 write-back behind flag; agent-gate session grant for online cloud use.
- [ ] 9.3 Two-phase confirm keywords; selector tables versioned per pack.
- [x] 9.4 **display** pack: headless-ish via Xvfb; one-time headed login/mic grant docs.
- [x] 9.5 **handoff** pack: prefer controller decision, keywords fallback; local STT → online turn + remainder inject; sticky vs one-shot; default off until verified.
- [x] 9.6 **system_audio** pack: PipeWire graph, allow/revoke, no self-echo; default off.
- [x] 9.7 **project** / **gpt** / **upload** / **canvas** / **capture** / **tasks** packs: one pack per web-only surface from design roadmap; each behind `features.yaml`; fail soft if DOM breaks.
