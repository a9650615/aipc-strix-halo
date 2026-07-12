# aipc-portal Specification Delta

## ADDED Requirements

### Requirement: Managed-service UI links

The portal SHALL surface a per-service "Open UI" link for any service card that
declares a `ui:` URL, so services that ship their own web console are reachable
from the Control Center.

#### Scenario: Service declares a UI

- **WHEN** a service card in `/etc/aipc/portal/services/` sets a `ui:` URL
- **THEN** the dashboard snapshot SHALL include that URL for the service
- **AND** the Services view SHALL render an Open UI link that opens it in a new tab.

#### Scenario: Service has no systemd unit

- **WHEN** a service card omits `systemd:` (its state resolves to `n/a`)
- **THEN** the Services view SHALL NOT render a Start button for it
- **AND** it SHALL show a status derived from the `health:` probe rather than a bare `n/a`.

### Requirement: Hermes WebUI service card

The portal SHALL list a Hermes WebUI service card pointing at the loopback
hermes-webui console.

#### Scenario: Hermes WebUI is running

- **WHEN** hermes-webui is serving on `127.0.0.1:8788`
- **THEN** the portal SHALL show the Hermes WebUI card as healthy
- **AND** its Open UI link SHALL open `http://127.0.0.1:8788/`.
