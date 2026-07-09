# Design — aipc-portal-v0

## Module boundaries

`system-aipc-portal` owns the entry portal only. It reads service
metadata files, probes optional systemd/health fields, and renders cards.
It has no Mem0-specific (or any service-specific) business logic.

Other modules appear solely by installing
`/etc/aipc/portal/services/<id>.yaml`.

## Network

Portal binds `127.0.0.1:7080` only. No remote management surface.

## Metadata contract

Required keys: `id`, `title`, `module`, `kind`.

Optional: `systemd`, `health`, `endpoint`, `ui`, `tags`, `notes`.

Unknown keys are ignored for forward compatibility.

## Runtime status

On each page load (and CLI status), the portal may:

- `systemctl is-active <systemd>` when declared
- HTTP GET `<health>` with a short timeout when declared

Failed probes do not crash the portal; cards show degraded/unknown.

## Live-host fallback

Before bootc switch, `/etc/aipc/portal/services` may be empty. The CLI
`aipc portal serve` runs the server from the repo module path and loads
metadata from `modules/*/files/etc/aipc/portal/services/` so operators get
value on the current AI PC without a rebuild.

## Build-time / runtime

`post-install.sh` only chmod + `systemctl enable` (no `--now`, no health
loops). Live HTTP checks belong in `verify.sh` when the unit is active.
