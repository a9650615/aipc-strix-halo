# system-aipc-portal

Local AIPC entry portal — the **manage** surface of the always-on closed
loop (`docs/voice-pipeline.md`, `docs/architecture.md` Phase 3): a
localhost homepage that lists manageable services declared under
`/etc/aipc/portal/services/*.yaml`.

The portal does not manage service internals and does not special-case
any consumer (including Mem0). Cards appear only because modules install
metadata.

**Voice open:** `aipc-voice-once` matches phrases like “打开 dashboard” /
“open portal” and runs `aipc portal open` (auto-starts serve if needed).

## Endpoint

`http://127.0.0.1:7080`

- `GET /` — HTML cards (auto-refresh ~5s) with unit/health probes
- `GET /healthz` — plain `ok`

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
