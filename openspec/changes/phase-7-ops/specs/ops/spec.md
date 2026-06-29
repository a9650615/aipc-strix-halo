## ADDED Requirements

### Requirement: BTRFS Snapshot Policy — Timeline 7d/4w/3m

The `ops-backup` module SHALL install snapper and configure a
timeline policy of 7 hourly + 4 weekly + 3 monthly snapshots
covering the `/`, `/var`, and `/home` BTRFS subvolumes. The
snapper timeline timer SHALL be enabled and active on a fresh
image.

#### Scenario: Snapper installed and configured for three subvols

- **WHEN** the image is freshly deployed
- **THEN** `which snapper` returns a path under `/usr` and
  `snapper list-configs` lists configs for `/`, `/var`, and
  `/home`

#### Scenario: Timeline timer active

- **WHEN** the image is freshly deployed
- **THEN** `systemctl is-active snapper-timeline.timer` returns
  `active`

#### Scenario: Timeline retention matches 7/4/3

- **WHEN** `snapper -c root get-config` is inspected
- **THEN** `TIMELINE_LIMIT_HOURLY=7`, `TIMELINE_LIMIT_WEEKLY=4`,
  and `TIMELINE_LIMIT_MONTHLY=3` are set

---

### Requirement: Pre-Update Snapshot Hook Fires Before bootc switch

The `ops-backup` module SHALL install a pre-update hook that
runs as the first step of `aipc update`, before any registry
call or `bootc switch` invocation. The hook SHALL create a
labelled snapshot (label format: `pre-update-<ISO timestamp>`)
on each of `/`, `/var`, and `/home`. Subsequent failures in
`aipc update` SHALL leave the snapshot in place.

#### Scenario: aipc update creates a pre-update snapshot

- **WHEN** the user runs `aipc update` against a tag whose digest
  differs from the currently installed image
- **THEN** before the `bootc switch` invocation, snapper records
  a snapshot on each of `/`, `/var`, `/home` with the label
  prefix `pre-update-`

#### Scenario: Snapshot persists when bootc switch fails

- **WHEN** `aipc update` runs and the `bootc switch` step fails
- **THEN** the pre-update snapshot remains listed by `snapper
  list` and is restorable via `aipc restore`

---

### Requirement: Doctor Aggregation — verify.sh + GPU + NPU + Services

The `ops-doctor` module SHALL extend `aipc doctor` with
aggregated checks: (a) the exit code of every module's
`verify.sh` printed as one row per module, (b) GPU status via
`rocm-smi` (device active, memory used, temperature), (c) NPU
status via `xdna-smi` (device active), and (d) `systemctl
is-active` for the core services `aipc-ollama.service`,
`aipc-litellm.service`, `aipc-postgres.service`,
`aipc-mem0.service`, `aipc-voice-pipecat.service`,
`aipc-agent.service`. Missing services from undeployed phases
SHALL report INFO, not FAIL.

#### Scenario: aipc doctor prints aggregated table

- **WHEN** `aipc doctor` is run on a freshly deployed image
- **THEN** the output contains sections for each deployed
  capability with per-module verify.sh status, a `gpu` row
  reporting rocm-smi output, an `npu` row reporting xdna-smi
  output, and a `services` block listing the core services with
  their `is-active` state

#### Scenario: Missing phases report INFO not FAIL

- **WHEN** `aipc doctor` runs and Phase 3 (`voice-pipecat`) is
  not deployed
- **THEN** the `services` row for `aipc-voice-pipecat.service`
  reports INFO with a one-line note naming the phase, and the
  overall doctor exit code is 0

---

### Requirement: Firstboot Wizard With Three Core Screens And Phase Plugin Surface

The `ops-firstboot` module SHALL ship a TUI wizard runner
invoked automatically on the primary user's first login (and via
`aipc init` on demand). The runner SHALL render three core
screens in order: (1) persona (name + voice — content
contributed by Phase 3), (2) editor confirm (Zed default —
content contributed by Phase 6, fallback to "Zed" if Phase 6
not deployed), (3) cloud API keys (paste → SOPS-encrypt → write
to `secrets/cloud-llm.yaml`). The runner SHALL read additional
screen contributions from `/etc/aipc/firstboot.d/*.yaml` and
SHALL render them in declared order between the core screens.

#### Scenario: Wizard runs on first login

- **WHEN** the primary user logs in for the first time on a
  freshly deployed image
- **THEN** the TUI wizard launches automatically and presents
  the three core screens in order

#### Scenario: Phase contribution screens render

- **WHEN** Phase 2 has dropped
  `/etc/aipc/firstboot.d/02-memory-rag.yaml` declaring its
  browser-consent and screen+audio screens
- **THEN** the wizard runner renders those screens at the
  declared position in the flow

#### Scenario: Idempotent rerun via aipc init

- **WHEN** the user runs `aipc init` after the wizard has
  previously completed
- **THEN** the wizard runs again, existing config files are
  preserved unless explicitly overwritten in the new pass, and
  the run completes without destroying user state

#### Scenario: Cloud key entry uses masked stdin

- **WHEN** the user is prompted for a cloud API key on the
  cloud-keys screen
- **THEN** the entered key is read via masked stdin (not echoed
  to the terminal), encrypted via SOPS using the user's age
  public key, and written to `secrets/cloud-llm.yaml`; the
  plaintext is not retained on disk

---

### Requirement: Weekly Image-Update Check With User-Consent Apply

The `ops-firstboot` module SHALL install `aipc-update.timer`
firing once per week, paired with `aipc-update.service` which
polls the configured tag for a newer digest. When a newer
digest is detected, the service SHALL emit a desktop notification
naming the new digest and the `aipc update` command. The image
SHALL NOT auto-apply updates and SHALL NOT auto-reboot. `aipc
update` SHALL be the only verb that performs `bootc switch`.

#### Scenario: Update timer active on fresh image

- **WHEN** the image is freshly deployed
- **THEN** `systemctl is-active aipc-update.timer` returns
  `active` and `systemctl list-timers aipc-update.timer` shows
  a next-fire time within 7 days

#### Scenario: New digest triggers notification, not apply

- **WHEN** `aipc-update.service` runs and the upstream tag's
  digest differs from the installed digest
- **THEN** a desktop notification is emitted and the file
  `/var/lib/aipc-update/available` is written with the new
  digest; no `bootc switch` is invoked and the system is not
  rebooted

#### Scenario: aipc update applies the update on user command

- **WHEN** the user runs `aipc update` while
  `/var/lib/aipc-update/available` declares a newer digest
- **THEN** the pre-update snapshot hook runs, `bootc switch`
  is invoked against the new digest, and the user is prompted
  to reboot at their convenience

---

### Requirement: Dual Update Channels — :stable Default, :rolling Opt-In

The `ops-firstboot` module SHALL declare `AIPC_UPDATE_TAG=stable`
in `/etc/aipc/branding.env` on a fresh image. Setting
`AIPC_UPDATE_TAG=rolling` SHALL switch `aipc-update.service` to
poll the `:rolling` tag. No other tag values SHALL be supported
in v1.

#### Scenario: Default tag is :stable

- **WHEN** the image is freshly deployed
- **THEN** `grep '^AIPC_UPDATE_TAG=' /etc/aipc/branding.env`
  prints `AIPC_UPDATE_TAG=stable`

#### Scenario: Channel switch takes effect on next cycle

- **WHEN** the user edits `/etc/aipc/branding.env` to set
  `AIPC_UPDATE_TAG=rolling` and `aipc-update.service` next fires
- **THEN** the service polls the `:rolling` tag and the
  available-update state under `/var/lib/aipc-update/` reflects
  that channel's digest

---

### Requirement: No Telemetry — Ops Modules Make No Outbound Calls Except Update Check

The `ops-backup`, `ops-doctor`, and `ops-firstboot` modules SHALL
NOT initiate outbound network traffic except for
`aipc-update.service`'s digest poll against the configured
container registry. No usage metrics, error pings, or aggregate
counts SHALL be sent to any host other than the configured
registry.

#### Scenario: No telemetry endpoints in any ops module config

- **WHEN** `grep -rE
  '(telemetry|metrics|sentry|posthog|segment|datadog|newrelic)'`
  is run against `modules/ops-backup/`, `modules/ops-doctor/`,
  `modules/ops-firstboot/`
- **THEN** the command exits non-zero (no matches found)

#### Scenario: Doctor runs make no outbound calls

- **WHEN** `aipc doctor` is run with network egress monitored
- **THEN** no outbound connections are made by any doctor
  subprocess

---

### Requirement: Restore CLI — aipc restore List And Apply

The `ops-backup` module SHALL ship `aipc restore` with at least
the verbs: `aipc restore list` (prints snapshots with id,
timestamp, label, size, and subvols), `aipc restore show <id>`
(prints snapshot details), and `aipc restore <id> [--subvols
a,b] --confirm` (rolls back the selected subvols; subvol switch
applies on the next reboot, which the command prompts for).
The CLI SHALL require `--confirm` before any irreversible
action.

#### Scenario: List prints expected columns

- **WHEN** `aipc restore list` is run on an image with at least
  one snapshot
- **THEN** the output includes columns for id, timestamp,
  label, size, and included subvols, one row per snapshot

#### Scenario: Apply without --confirm fails safely

- **WHEN** `aipc restore <id>` is run without `--confirm`
- **THEN** the command exits non-zero with a message naming
  the required flag and the user-visible side effects; no
  rollback occurs

#### Scenario: Apply with --confirm rolls back on reboot

- **WHEN** the user runs `aipc restore <id> --confirm`
- **THEN** snapper applies the rollback to the selected
  subvols, the command prompts the user to reboot, and after
  reboot the rolled-back subvols are the live ones
