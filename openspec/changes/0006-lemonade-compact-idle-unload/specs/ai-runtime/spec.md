## ADDED Requirements

### Requirement: Compact Aliases May Opt Into Idle Release

Lemonade-backed model aliases MAY declare `idle_unload_after_s` in
`models.yaml`. When present, the runtime SHALL unload that alias after it has
been loaded and idle for at least the configured number of seconds, provided
the model is not pinned or in use.

The initial shipped consumer of this policy is `coder-compact`, which SHALL
idle-unload after `300s` of inactivity. Other aliases remain unaffected unless
they explicitly opt in.

#### Scenario: coder-compact releases after five minutes idle

- **WHEN** `coder-compact` has been loaded, receives no traffic for 300
  seconds, and remains unpinned and not in use
- **THEN** the Lemonade idle-release job unloads it and it no longer appears in
  `all_models_loaded`

#### Scenario: Pinned or active models are not unloaded

- **WHEN** a loaded Lemonade model is marked `pinned` or `in_use`
- **THEN** the idle-release job leaves it loaded even if its last-use age
  exceeds the configured threshold

#### Scenario: Other aliases are unaffected unless they opt in

- **WHEN** a Lemonade-backed alias does not declare `idle_unload_after_s`
- **THEN** the idle-release job never unloads it due to idleness alone
