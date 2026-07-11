## ADDED Requirements

### Requirement: Dashboard Reports Compact Idle Release

The Control Center dashboard SHALL report the configured compact model's
idle-release state together with the idle-release timer state. The backend
SHALL derive Lemonade idle age using the host monotonic clock and SHALL keep
Lemonade timestamp interpretation out of the browser.

#### Scenario: Compact model is unloaded

- **WHEN** `coder-compact` does not appear in Lemonade's loaded-model list
- **THEN** the Runtime card shows that Compact is unloaded
- **AND** it shows the configured automatic-release timeout and timer state

#### Scenario: Compact model is in use

- **WHEN** Lemonade reports the configured compact model as `in_use`
- **THEN** the Runtime card shows that Compact is in use
- **AND** it does not show a release countdown

#### Scenario: Compact model is idle

- **WHEN** Lemonade reports the configured compact model as loaded and not in use
- **THEN** the Runtime card shows its current idle duration
- **AND** it shows the remaining time until the configured release threshold

#### Scenario: Status source is unavailable

- **WHEN** the manifest, Lemonade status, or timer status cannot be read
- **THEN** the compact status degrades to unknown
- **AND** the rest of the dashboard snapshot remains available

#### Scenario: Dashboard remains observational

- **WHEN** the Runtime card displays compact idle-release status
- **THEN** it does not expose a manual unload action
