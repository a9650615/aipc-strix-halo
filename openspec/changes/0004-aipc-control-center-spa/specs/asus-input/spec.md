# asus-input Specification Delta

## ADDED Requirements

### Requirement: Device state publication

The Asus input module SHALL expose observed Command Center button and declared
I/O state changes to the local portal through a bounded, localhost-only
integration contract.

#### Scenario: Command Center button is observed

- **WHEN** the module observes a Command Center button transition
- **THEN** it SHALL publish a timestamped state event for the portal
- **AND** it SHALL preserve the existing button action.

#### Scenario: Hardware is unavailable

- **WHEN** the expected input device cannot be discovered
- **THEN** the module SHALL publish or permit an explicit unavailable state
- **AND** it SHALL not fail unrelated portal functionality.
