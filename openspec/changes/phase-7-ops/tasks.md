## 1. Module Scaffolding (3 modules)

- [ ] 1.1 `ops-backup`: create `modules/ops-backup/` with README,
  packages.txt (snapper), files/ for snapper configs for `/`,
  `/var`, `/home` and the pre-update hook script, post-install.sh
  (enable snapper-timeline.timer, install pre-update hook),
  verify.sh (snapper installed, three configs present, timeline
  timer active, hook script executable).
- [ ] 1.2 `ops-doctor`: create `modules/ops-doctor/` with README,
  files/ for the doctor-extension Python (or shell) module under
  `tools/aipc_lib/doctor/`, verify.sh (doctor entry-point runs
  and prints the expected sections).
- [ ] 1.3 `ops-firstboot`: create `modules/ops-firstboot/` with
  README, packages.txt (textual or rich for TUI), files/ for the
  wizard runner under `/usr/libexec/aipc-firstboot`, the systemd
  unit that runs it on first login, `aipc-update.timer` +
  `aipc-update.service`, `/etc/aipc/branding.env`,
  `/etc/aipc/firstboot.d/00-ops.yaml` declaring the three core
  screens, verify.sh (wizard binary present, timer/service units
  loadable, branding.env present with default tag).

## 2. Snapper Configuration

- [ ] 2.1 `snapper -c root create-config /` (or equivalent
  packaged config drop) producing the three configs.
- [ ] 2.2 Set timeline limits to 7 hourly / 4 weekly / 3 monthly
  on each config.
- [ ] 2.3 Enable `snapper-timeline.timer` and `snapper-cleanup.timer`.
- [ ] 2.4 Document the policy in `ops-backup/README.md`.

## 3. Pre-Update Snapshot Hook

- [ ] 3.1 Script under `/etc/bootc/triggers.d/00-aipc-pre-update`
  (or the `aipc update` command, whichever path bootc supports)
  that runs as step 1 of `aipc update`. Creates labelled
  snapshots on `/`, `/var`, `/home`.
- [ ] 3.2 Confirm idempotency: if the hook runs twice in the same
  second, the second invocation is a no-op (label deduplicates by
  ISO timestamp).
- [ ] 3.3 Verify the snapshot persists when downstream steps fail.

## 4. Doctor Extension

- [ ] 4.1 Extend `tools/aipc_lib/doctor.py` (or its equivalent)
  with three new check groups:
  - `gpu`: parse `rocm-smi` output for active GPU, memory, temp.
  - `npu`: parse `xdna-smi` output for active NPU.
  - `services`: run `systemctl is-active` for ollama, litellm,
    postgres, mem0, voice-pipecat, agent.
- [ ] 4.2 INFO when a phase isn't deployed (service unit missing →
  INFO not FAIL).
- [ ] 4.3 Doctor verify.sh runs the doctor end-to-end and exits 0
  (with INFOs allowed) on a freshly built image.

## 5. Firstboot Wizard Runner

- [ ] 5.1 TUI wizard binary `/usr/libexec/aipc-firstboot`:
  enumerates `/etc/aipc/firstboot.d/*.yaml`, renders core screens
  interleaved with phase contributions per their declared
  ordering.
- [ ] 5.2 Persona screen (core, with Phase 3 content plugged in):
  name + voice preset / clone sample.
- [ ] 5.3 Editor confirm screen (core, with Phase 6 content
  plugged in): Zed default with switch option.
- [ ] 5.4 Cloud-keys screen (core): masked stdin, SOPS-encrypt,
  write to `secrets/cloud-llm.yaml`.
- [ ] 5.5 Systemd unit (`aipc-firstboot.service` triggered by a
  marker file at `/var/lib/aipc-firstboot/done`) runs once per
  primary user account.
- [ ] 5.6 `aipc init` CLI: re-runs the wizard idempotently.

## 6. Update Timer + Apply Command

- [ ] 6.1 `aipc-update.timer` (OnCalendar=weekly) + `aipc-update.service`
  (oneshot polling the configured tag).
- [ ] 6.2 On newer digest detected: write
  `/var/lib/aipc-update/available` with the digest; emit a
  desktop notification (via `notify-send` in the user session).
- [ ] 6.3 `aipc update` CLI verb: runs pre-update hook → reads
  available digest → `bootc switch` → prompts the user to reboot.
- [ ] 6.4 No auto-apply, no auto-reboot, no scheduled reboot.

## 7. Update Channels

- [ ] 7.1 Default `/etc/aipc/branding.env` with
  `AIPC_UPDATE_TAG=stable`.
- [ ] 7.2 `aipc-update.service` reads the env file at runtime;
  channel switch takes effect on the next cycle.
- [ ] 7.3 Document the switch procedure in
  `ops-firstboot/README.md`.

## 8. No-Telemetry Guarantee

- [ ] 8.1 Grep guard in `verify.sh` for each of the three modules:
  no `telemetry|metrics|sentry|posthog|segment|datadog|newrelic`
  strings in module config.
- [ ] 8.2 Doctor + wizard + backup runs with network egress
  monitoring: only outbound traffic during the update poll, only
  to the configured registry.

## 9. Restore CLI

- [ ] 9.1 `aipc restore list` — prints snapper snapshots with id,
  timestamp, label, size, subvols.
- [ ] 9.2 `aipc restore show <id>` — prints snapshot details.
- [ ] 9.3 `aipc restore <id> [--subvols a,b] --confirm` — applies
  the rollback (snapper `undochange` or equivalent) and prompts
  for reboot.
- [ ] 9.4 Refuse without `--confirm`; print expected flag and
  side-effects in the error.

## 10. Doctor Self-Check

- [ ] 10.1 `aipc doctor` includes itself: a row asserting that
  `tools/aipc doctor` is callable and exits 0 (or INFO for
  undeployed phases).
- [ ] 10.2 Snapshot policy check: confirms timeline timer active +
  pre-update hook present.
- [ ] 10.3 Update channel check: confirms tag is one of
  `stable`/`rolling` and update timer next-fire is within 7 days.
- [ ] 10.4 Wizard completion check (INFO): confirms
  `/var/lib/aipc-firstboot/done` exists.

## 11. Documentation

- [ ] 11.1 Per-module README for each of the 3 modules.
- [ ] 11.2 `docs/ops.md`: snapshot policy, update flow, channel
  switching, restore procedure, no-telemetry stance.
- [ ] 11.3 Confirm `docs/architecture.md §7` Phase 7 row matches
  the 3-module list shipped here (no count change to the §7
  header total).

## 12. Local Build Verification

- [ ] 12.1 Run `tools/aipc render bootc`; confirm Containerfile
  includes all 3 ops modules.
- [ ] 12.2 Run `tools/aipc render ansible --check`; confirm it
  lints clean.
- [ ] 12.3 Run each module's `verify.sh` in a privileged container.

## 13. AI PC Hardware Verification

- [ ] 13.1 Deploy `:rolling` tag to the AI PC via `bootc switch`.
- [ ] 13.2 Run `aipc doctor` on the AI PC; confirm GPU + NPU +
  services sections populated.
- [ ] 13.3 Boot fresh user account; confirm firstboot wizard
  launches automatically.
- [ ] 13.4 Run the wizard end-to-end; confirm
  `secrets/cloud-llm.yaml` is created (SOPS-encrypted) and
  `/var/lib/aipc-firstboot/done` exists.
- [ ] 13.5 Wait for or trigger `aipc-update.service`; confirm
  notification fires when a new digest is available; run `aipc
  update`; confirm pre-update snapshots exist.
- [ ] 13.6 Run `aipc restore list`; pick a snapshot; `aipc
  restore <id> --confirm`; reboot; confirm rolled-back subvols.
- [ ] 13.7 Switch `AIPC_UPDATE_TAG=rolling`; confirm next cycle
  polls the rolling tag.

## 14. Archive Change

- [ ] 14.1 Run `npx -y @fission-ai/openspec validate phase-7-ops
  --strict` — must print `Change 'phase-7-ops' is valid`.
- [ ] 14.2 Run `npx -y @fission-ai/openspec archive phase-7-ops`
  to merge the spec into `openspec/specs/ops/spec.md` and close
  the change.
