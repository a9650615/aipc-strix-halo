# aipc-portal Specification Delta

## ADDED Requirements

### Requirement: Control Center SPA

The portal SHALL serve a localhost-only Astro-built single-page web app and
retain client-side navigation between Home, Device, AI & Voice, and Services.

#### Scenario: Browser opens the portal

- **WHEN** an operator opens the portal URL
- **THEN** the Home view SHALL render without requiring a separate dashboard URL
- **AND** navigation between portal views SHALL not perform a full document load.

### Requirement: Migrated dashboard snapshot

The portal SHALL expose the existing status-dashboard service and model
observations through a versioned JSON snapshot API.

#### Scenario: Legacy status data is available

- **WHEN** the portal refreshes its dashboard snapshot
- **THEN** it SHALL include equivalent service state and loaded-model facts
- **AND** the old dashboard HTML SHALL not be a required user-facing surface.

### Requirement: Explicit unavailable states

The portal SHALL render unavailable device or platform data explicitly without
preventing unrelated dashboard sections from rendering.

#### Scenario: Input source is absent

- **WHEN** a device state source is unavailable
- **THEN** the Device view SHALL label that source unavailable with a diagnostic
- **AND** it SHALL not display a fabricated active or healthy state.
