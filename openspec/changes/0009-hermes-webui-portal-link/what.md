# What — hermes-webui-portal-link

## Scope

1. **Dashboard snapshot** (`dashboard.py`): each entry in the `services` list of
   `/api/v1/dashboard` gains two fields — `ui` (from the service card's `ui:`)
   and `health` (the boolean `health_ok` probe result). No other snapshot shape
   changes.

2. **Portal SPA** (`web/src/pages/index.astro`, rebuilt into `static/`): the
   Managed services list renders per service:
   - a state label that, for services without a systemd unit (`state == "n/a"`),
     shows `ready`/`down`/`n/a` derived from `health` instead of the bare `n/a`;
   - the Start button **only** when the service is systemd-backed
     (`state != "n/a"`), so cards with no unit stop showing a button that 400s;
   - an **Open UI** link (`target=_blank`, `rel=noopener`) whenever `ui` is set.

3. **Service card** (`agent-orchestrator/files/etc/aipc/portal/services/hermes-webui.yaml`):
   a new card for hermes-webui — `id: hermes-webui`, `kind: agent`,
   `health: http://127.0.0.1:8788/health`, `endpoint: http://127.0.0.1:8788`,
   `ui: http://127.0.0.1:8788/`, no `systemd:` (phase A: home-managed).

## Out of scope

- Packaging hermes-webui as an image module / systemd unit (deferred phase B).
- Auth, remote/phone access, self-update policy — kept at conservative loopback
  defaults, no change here.
