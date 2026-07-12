## ADDED Requirements

### Requirement: Consumer Model Lists Sync From The Gateway, Not By Hand

Registered AI consumers with static model lists (OpenCode, CCS, Hermes) SHALL
be updatable to LiteLLM's live `/v1/models` alias set via a single
`aipc providers sync` command, and `aipc models sync` SHALL run that
propagation automatically after a successful pull. A consumer whose config is
absent SHALL be skipped with a diagnostic, not fail the run.

#### Scenario: Model swap converges every consumer

- **WHEN** a model alias is added or its backing model swapped in models.yaml
  and `aipc models sync` completes a pull
- **THEN** OpenCode, CCS, and Hermes configs list the current alias set
  without further manual edits

#### Scenario: Hermes config is rewritten safely

- **WHEN** the Hermes sync rewrites `~/.hermes/config.yaml`
- **THEN** the original is kept as a timestamped backup and the replacement
  is written atomically, preserving all non-provider config keys

### Requirement: Weight Sync Detects Swapped Models And Registers Custom Pulls

`aipc models sync` SHALL detect when the model behind an alias has changed
(recorded synced `model_id` differs from the manifest) and re-pull it;
`aipc models list` SHALL surface that state as `stale`. Manifest entries MAY
declare `checkpoints`/`recipe`/`label`, from which sync SHALL build the
`user.`-prefixed custom Lemonade registration pull.

#### Scenario: Swapped alias re-syncs

- **WHEN** models.yaml changes an alias's `model_id` after a prior successful
  sync
- **THEN** `list` reports the alias `stale` and the next `sync` pulls the new
  model

#### Scenario: Custom registration pulls without hand-typed commands

- **WHEN** a lemonade entry declares `checkpoints:`
- **THEN** sync issues `lemonade pull user.<model_id> --checkpoint <slot>
  <ref> ... --recipe <recipe>` instead of a bare catalog pull
