# Design — AIPC Control Center SPA

## Architecture

`system-aipc-portal` remains the localhost-only runtime service. It serves
Astro-generated static assets and exposes JSON/SSE endpoints. Astro's client
router provides SPA navigation; only the live cards hydrate on the client.

The old status dashboard becomes a Python snapshot provider. Its service
discovery, unit state, endpoint health, and loaded-model queries are reused;
its HTML is not retained.

```text
browser SPA
  ├── GET /api/v1/dashboard       initial and periodic snapshot
  └── GET /api/v1/device/events   bounded SSE I/O updates
          │
          └── portal adapters
                ├── old status-dashboard probes
                ├── portal service metadata/probes
                └── Asus input event/state source
```

## Views

- **Home**: operating profile, AI MAX+ platform summary, voice/agent health,
  and a compact Z13 I/O summary.
- **Device**: a hand-authored SVG Z13 Flow silhouette with labelled button and
  port positions; each marker is `active`, `idle`, `unavailable`, or
  `disconnected`, never inferred as healthy merely because it exists.
- **AI & Voice**: migrated model/runtime information and closed-loop status.
- **Services**: migrated service cards, technical detail, and existing
  controlled start actions.

The Device view and platform telemetry are sibling views: the former reports
what the Z13 chassis exposes, the latter reports what the AI MAX+ 395 platform
is doing. Both remain visible in Home.

## API contract

`GET /api/v1/dashboard` returns `{services, models, platform, device}`.
Missing or unreadable sources are represented with an `availability` field and
a short diagnostic, not omitted or fabricated.

`GET /api/v1/device/events` emits only newly observed device-state transitions.
The server retains a small in-memory recent-event buffer for new clients; it
does not create a second event database.

Existing start and cancel POST endpoints retain their current access controls.

## Errors and verification

The SPA renders an unavailable state per card and keeps all other cards usable
when a probe fails. Test coverage verifies snapshot serialization, event
availability semantics, SVG marker mapping, migration parity for legacy data,
and retained controlled actions. Static and both render targets are required;
hardware verification additionally exercises the physical Command Center
button and real I/O transitions.
