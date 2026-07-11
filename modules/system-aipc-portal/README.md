# system-aipc-portal

Local AIPC entry portal — the **manage** surface of the always-on closed
loop (`docs/voice-pipeline.md`, `docs/architecture.md` Phase 3): a
localhost console for closed-loop health, live agent work, and declared
services under `/etc/aipc/portal/services/*.yaml`.

The homepage is status-first (not an endpoint directory): closed-loop
strip (hear → think → speak → remember → manage), quick CLI chips,
start actions for declared units, and service cards grouped by kind.
Technical endpoint detail stays under a collapsible section.

## Control Center SPA

The portal serves Astro-built assets from the same localhost Python service;
Node is used only to rebuild `web/` during development. `npm run build` in
`web/`, then copy `web/dist/` into `files/usr/lib/aipc-portal/static/` before
committing a frontend change.

`/api/v1/dashboard` is the SPA snapshot endpoint. It combines declared service
status, Lemonade's loaded models, XDNA NPU availability, and the latest
Command Center state published at `/run/aipc/command-center.json`. An absent
device source is displayed as unavailable rather than healthy.

The portal does not special-case any consumer (including Mem0). Cards and
stage membership come from metadata tags/kind only.

**Voice open:** `aipc-voice-once` matches phrases like “打开 dashboard” /
“open portal” and runs `aipc portal open` (auto-starts serve if needed).

## Endpoint

`http://127.0.0.1:7080`

- `GET /` — manage console (auto-refresh ~5s): loop strip, ops, live work, cards
- `GET /healthz` — plain `ok`
- `POST /services/<id>/start` — start that card’s declared systemd unit
- `POST /ops/baseline/start` — start all cards tagged `baseline` with a unit
- `POST /automation/<task_id>/cancel` — proxy cancel to agent-orchestrator
## CLI

```bash
aipc portal          # URL + card summary
aipc portal open     # open browser (auto-starts server if down)
aipc portal serve    # foreground server (live-host / pre-bootc fallback)
aipc voice status    # closed-loop probe including portal health
```

On hosts that have not yet bootc-switched this module, `serve` loads
metadata from the repo tree under
`modules/*/files/etc/aipc/portal/services/`.

## Layout

```text
files/usr/lib/aipc-portal/aipc_portal/   # stdlib HTTP package
files/etc/systemd/system/aipc-portal.service
files/etc/aipc/portal/services/aipc-portal.yaml  # self-card
env/endpoint
```

## Dependencies

None required. Other modules optionally install portal metadata.

## Verification

- Static/render: `verify.sh` syntax + self metadata.
- Hardware: active `aipc-portal.service`, `GET /healthz`, `aipc portal open`.

## Spec

`openspec/changes/aipc-portal-v0/`
