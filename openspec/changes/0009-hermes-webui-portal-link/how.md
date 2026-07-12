# How — hermes-webui-portal-link

## dashboard.py

In `snapshot()`, extend the services comprehension:

```python
services = [
    {
        "id": item.meta.id,
        "title": item.meta.title,
        "state": item.unit_state,
        "ui": item.meta.ui,
        "health": item.health_ok,
    }
    for item in statuses
]
```

`item.meta.ui` and `item.health_ok` already exist on `ServiceStatus`/`ServiceMetadata`.

## index.astro

Replace the services `.map(...)` body so it gates the Start button on a
systemd-backed state, derives a health label for `n/a` services, and appends an
Open UI anchor when `s.ui` is present. Rebuild with `npm run build` in `web/`
and copy `web/dist/index.html` → `files/usr/lib/aipc-portal/static/index.html`
(the repo's documented build→copy step; Node is dev-time only, not in the image).

## Service card

Add `hermes-webui.yaml` under agent-orchestrator's portal services dir. No
`systemd:` key — the portal probes `health:` (HTTP 200 = ok) and, because the
SPA now hides Start for unit-less services, shows only status + Open UI.

## Render parity (§4)

All three edits are plain module files copied identically by both the bootc
Containerfile and the ansible site.yml — no renderer special-casing, so bootc
and ansible stay in sync by construction.

## Verification

- Static: `pytest` (portal contract tests), `py_compile dashboard.py`.
- Render: `tools/aipc render bootc`, `tools/aipc render ansible --check`.
- Hardware: live portal at `:7080` shows the Hermes WebUI card with a working
  Open UI link to `:8788`, and hermes-webui's session bridge lists the
  `aipc-voice` Hermes sessions.
