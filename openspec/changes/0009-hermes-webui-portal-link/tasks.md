# Tasks — hermes-webui-portal-link

- [x] 1. Add `ui` + `health` fields to the `services` entries in
      `dashboard.py` `snapshot()`.
- [x] 2. Update `index.astro` services renderer: health-derived label for
      unit-less services, Start button only when systemd-backed, Open UI link
      when `ui` is set. Rebuild Astro and copy `dist/index.html` into `static/`.
- [x] 3. Add `hermes-webui.yaml` service card under agent-orchestrator.
- [x] 4. Static + render verification (pytest 16 passed, bootc+ansible renders
      both exit 0 and include both modules symmetrically → §4 parity).
- [~] 5. Hardware-verify. DONE (via repo code, live probe): `dashboard.snapshot()`
      against the running hermes-webui returns the card with `ui` +
      `health: true`; hermes-webui on `:8788` lists the `aipc-voice` Hermes
      sessions. PENDING: the *deployed* portal at `:7080` runs the pre-card
      ostree image (`services: []` even for existing cards) — the card shows only
      after a bootc rebuild+reboot or a live-hotfix of the running portal.
