# hermes-webui Specification Delta

## ADDED Requirements

### Requirement: Reproducible Hermes WebUI integration

The system SHALL provide the Hermes WebUI console as a repo module so a rebuilt
image brings it up automatically, without freezing the self-updating,
agent-coupled app into the read-only image.

#### Scenario: Fresh image first boot

- **WHEN** a freshly built image boots with a primary user present
- **THEN** a setup oneshot SHALL provision `~/.hermes/hermes-webui` at the pinned
  ref and enable lingering for that user
- **AND** the Hermes WebUI user service SHALL start on `127.0.0.1:8788`.

#### Scenario: hermes-agent not yet present

- **WHEN** the agent checkout at `~/.hermes/hermes-agent` is absent
- **THEN** the Hermes WebUI user service SHALL stay dormant (its
  `ConditionPathExists` unmet) rather than crash-loop.

### Requirement: Reboot persistence

The Hermes WebUI service SHALL survive reboot without manual intervention.

#### Scenario: Machine reboots

- **WHEN** the machine reboots after setup has completed
- **THEN** the Hermes WebUI user service SHALL start automatically via linger and
  the shipped auto-enable symlink.
