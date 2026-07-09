# aipc-portal Spec

## ADDED Requirements

### Requirement: AIPC Entry Portal Module

The system SHALL provide a first-class `system-aipc-portal` module that
runs a local web entry portal using a stdlib (or equivalently minimal)
HTTP server.

#### Scenario: Portal binds locally

- **WHEN** the portal service starts
- **THEN** it listens on `127.0.0.1` only
- **AND** it does not expose a remote management listener

#### Scenario: Portal discovers services from metadata

- **WHEN** metadata files exist under `/etc/aipc/portal/services/*.yaml`
- **THEN** the portal renders one card per valid metadata file
- **AND** invalid metadata files do not prevent valid cards from rendering

#### Scenario: Empty registry still serves

- **WHEN** the services directory is missing or empty
- **THEN** the portal still returns HTTP 200 for `/` and `/healthz`

#### Scenario: Cards show live status when declared

- **WHEN** a card declares `systemd` and/or `health`
- **THEN** the portal probes those fields and displays unit and health status
- **AND** probe failures are shown as degraded without crashing the page

### Requirement: Portal Metadata Contract

Modules SHALL declare manageable services through metadata files rather
than portal-specific code. The portal SHALL NOT hardcode Mem0 or other
service business logic.

#### Scenario: Mem0 appears via metadata

- **WHEN** `memory-mem0` installs `mem0.yaml`
- **THEN** the portal shows a Mem0 card using declared endpoint/health
- **AND** any UI link is whatever the module declared (may be null)

#### Scenario: Unknown keys ignored

- **WHEN** a metadata file contains keys beyond the known contract
- **THEN** the portal still loads the card and ignores unknown keys

### Requirement: Portal CLI

The `aipc` CLI SHALL provide `aipc portal`, `aipc portal open`, and
`aipc portal serve`.

#### Scenario: User asks for portal status

- **WHEN** the user runs `aipc portal`
- **THEN** the command prints the portal URL and a one-line summary of
  declared cards (with probes when possible)

#### Scenario: User opens portal

- **WHEN** the user runs `aipc portal open`
- **THEN** the command opens the portal URL with the system browser helper

#### Scenario: Live-host serve fallback

- **WHEN** the portal unit is not installed or not active
- **AND** the user runs `aipc portal serve`
- **THEN** a foreground server starts on `127.0.0.1:7080` using the
  module package path and/or repo tools fallback
