## Context

The image is immutable; the user is not. Every other phase ships
features the user touches — voice, agents, memory, dev tools, games.
Phase 7 ships the safety net underneath:

1. **Snapshots**: BTRFS subvolumes via snapper. Timeline coverage
   (hourly / weekly / monthly) for incidents the user causes;
   pre-update snapshots for incidents the image causes.
2. **Doctor**: one command that reads the truth out of every
   subsystem — GPU temp + memory, NPU active, every quadlet
   `systemctl is-active`, every module's `verify.sh` exit code.
3. **Firstboot wizard**: 3 minutes from first login to a working
   personalised assistant. Owns the runner; Phase 2 and Phase 3
   plug in screens.
4. **Updates**: weekly check, user-consent apply, dual channels.
   Never auto-apply, never auto-reboot, never silently downgrade.
5. **No telemetry**: zero outbound traffic from ops modules. The
   AI PC is private by default; opt-in is the only path to exfil.

The design is opinionated about mechanism (snapper, systemd
timers, bootc tags) and unopinionated about timing (user picks
when to update, when to restore, when to run the wizard).

## Goals / Non-Goals

**Goals:**

- The user can break and recover the box without leaving the
  shell: `aipc snap list` → `aipc restore <id>` → reboot.
- The user knows the box's health in one command: `aipc doctor`
  produces a single-screen table.
- Onboarding is ≤3 minutes from first login to working assistant.
- The user is in charge of update timing: the timer informs; the
  command applies.
- The image is private by default and stays that way.

**Non-Goals:**

- Cluster-scale ops (multiple AI PCs in lockstep). Single-host.
- Centralised log aggregation. journald is the truth; no
  forwarding.
- Crash-reporting daemons. journald + snapper covers recovery;
  per-process crash dumps stay local.
- Auto-restore on boot failure. bootc already handles boot-tier
  rollback; we don't add a second mechanism.
- A graphical wizard. TUI by default (Q2 — open for revisit). The
  image ships without a display dependency for `aipc init`.

## Decisions

**D1 — Snapper policy: timeline (7d/4w/3m) + pre-update**

*Chosen:* snapper config covers `/`, `/var`, `/home`. Timeline
profile: 7 hourly + 4 weekly + 3 monthly. Pre-update snapshots
fire before every `bootc switch` (via a hook installed in
`/etc/bootc/triggers.d/` or equivalent).

*Alternatives:*
- Pre-update only: loses casual rollback ("I just messed up my
  fish config, can I undo?").
- 30 daily snapshots: heavy on disk for marginal value.
- No snapper, rely on bootc rollback: bootc rolls system, not
  `/var` and `/home` data. User-data rollback needs snapper.

*Why chosen:* The 7/4/3 profile is snapper's well-tuned default;
disk cost is bounded by the BTRFS dedup; user-data subvols
included so a config edit gone wrong is recoverable.

**D2 — Doctor extension: verify.sh aggregate + GPU + NPU + services**

*Chosen:* `aipc doctor` aggregates each module's `verify.sh` exit
code into a section header, then prints additional rows for: GPU
status (rocm-smi: device active, memory used, temperature), NPU
status (xdna-smi: device active), and `systemctl is-active` for
the core services (ollama, litellm, postgres, mem0, pipecat,
agent).

*Alternatives:*
- verify.sh only: cheaper, but the user has to read 40+ lines to
  spot one red entry.
- Grafana dashboard: overkill, requires a display.
- Vendor monitoring (Prometheus + alertmanager): great for a fleet,
  not for one box.

*Why chosen:* One screen, one command, all green / red signals
visible at once. Matches the existing `aipc doctor` shape from
Phases 0–6.

**D3 — Firstboot wizard: 3 screens, owned by `ops-firstboot`,
extensible**

*Chosen:* Three core screens — (1) persona (name + voice — joint
with Phase 3), (2) editor confirm (Zed default — pulled from
Phase 6), (3) cloud API keys (paste → SOPS-encrypt → write
secrets file). The runner is a TUI; other phases plug in
additional screens (Phase 2's browser-consent + screen+audio,
Phase 3's wake-word recording).

The runner reads a list of screen-contribution files from
`/etc/aipc/firstboot.d/`; each phase drops a YAML manifest naming
its screens, ordering hints, and the script that renders them.

*Alternatives:*
- A long wizard with every prompt baked in: annoying, hard to
  trim.
- No wizard: user lost, no clear onboarding path.

*Why chosen:* 3 minutes covers the must-have path; the
contribution mechanism lets other phases extend the wizard without
touching `ops-firstboot`.

**D4 — Updates: weekly check + user-consent apply, never automatic**

*Chosen:* `aipc-update.timer` runs once a week. The associated
oneshot service polls the configured tag (`:stable` or `:rolling`)
on the upstream registry. If a newer digest is available, a
desktop notification appears with a one-line summary plus the
`aipc update` command. Running `aipc update` does the `bootc
switch`; the new image takes effect on the next reboot, which the
user initiates.

*Alternatives:*
- Daily check: too frequent for the actual cadence of upstream
  releases.
- Manual only: users forget; security patches sit unapplied.
- Auto-apply: forced reboot is hostile UX; explicitly out per
  user direction.

*Why chosen:* User direction was explicit — "不要 force update".
Weekly poll + notification + user command is the right shape.

**D5 — Update tracking tag: `:stable` default, `:rolling` opt-in**

*Chosen:* `/etc/aipc/branding.env` declares
`AIPC_UPDATE_TAG=stable` by default. Setting `AIPC_UPDATE_TAG=rolling`
flips the update check to the rolling channel. Channel switch
takes effect on the next update cycle (or immediately if `aipc
update` is invoked after the change).

*Alternatives:*
- Single tag: no test channel; breaking changes hit everyone at
  once.
- Three+ tags: more channels than the project produces.

*Why chosen:* Dual-track lets the project ship breaking changes
to `:rolling` users (who opt in to early-warning) without
disrupting `:stable` users. The two tags are also what existing
phases (Phase 6 D-section) already assume.

**D6 — No telemetry**

*Chosen:* Zero outbound network traffic from `ops-backup`,
`ops-doctor`, or `ops-firstboot`. The update check is the *only*
outbound network call any ops module makes, and it goes to the
configured container registry — nowhere else. No usage metrics,
no error pings, no anonymised aggregate counts.

*Alternatives:*
- Anonymised usage metrics (opt-in): could improve defaults over
  time; explicitly off the table for v1 because the user
  signalled "no telemetry, full stop".

*Why chosen:* Consistent with Phase 2 D5 (local-only data plane)
and the broader privacy posture. The user gets to see every byte
that leaves the box.

**D7 — Restore CLI: `aipc restore`**

*Chosen:* `aipc restore` is a thin wrapper over snapper. `aipc
restore list` prints snapshots with timestamp, label, size,
subvols included; `aipc restore <id> [--subvols a,b]` does the
rollback (requires `--confirm` for irreversibility). On reboot
the rolled-back subvols are the live ones.

*Alternatives:*
- Use snapper directly: works, but the user has to remember the
  per-subvol incantation.
- A GUI: out of scope; TUI suffices.

*Why chosen:* Discoverability and a single mnemonic verb. The
underlying mechanism is still snapper; the wrapper is ~50 lines.

## Risks / Trade-offs

- **Snapper disk consumption**: timeline + pre-update can grow
  on a 1 TB SSD. **Mitigation**: snapper's BTRFS dedup keeps the
  effective cost low; doctor warns when free space drops below a
  configurable threshold (default 20 GiB).
- **Pre-update hook timing**: if the hook fires after `bootc switch`
  has already begun mutating, the snapshot misses the "before"
  state. **Mitigation**: the hook is the *first* step of `aipc
  update`, before any registry call, so the snapshot is always
  pre-mutation.
- **Wizard fragility**: a stuck wizard blocks first login. **Mitigation**:
  the wizard runner is killable (any Ctrl-C resumes the shell);
  failed screens are skippable with a clear "you can finish this
  later via `aipc init`" message; rerunning is idempotent.
- **Update notification missed**: desktop notification expires;
  user never sees it. **Mitigation**: `aipc doctor` reports
  "update available since <date>" as INFO; the state file under
  `/var/lib/aipc-update/` persists across boots.
- **Restore conflicts with live state**: rolling back `/home`
  while files are open. **Mitigation**: restore prompts for a
  reboot before applying (subvol switch happens at boot); user
  closes their session first.
- **Cloud-key paste in TUI scrollback (Q3)**: pasting a long API
  key into a TUI text field leaves it in terminal scrollback.
  **Mitigation**: the wizard's key-entry uses stdin masked input
  (like `read -s`), never echoing the key; the SOPS-encrypted
  blob is the only persistent form.

## Migration Plan

No prior ops surface exists on this image. Phase 7 is net-new.
Ordering:

1. Phase 0 (foundation) ships the bootc setup that pre-update
   hooks need; Phase 7 depends on Phase 0 having landed.
2. Phase 1 ships the `cloud-llm-fallback` change's secrets
   format; Phase 7's cloud-key wizard screen writes the same
   secrets file shape.
3. Phase 2 and Phase 3 contribute additional firstboot screens;
   they ship their contributions in their own modules, plugged in
   via `/etc/aipc/firstboot.d/`.

`aipc init` is the migration path for users who skipped the
firstboot wizard or who reset state: it re-runs the wizard
end-to-end and is idempotent (existing config files are
preserved unless the user explicitly overwrites them).

## Open Questions

- **Q1 — Snapper vs btrbk**: snapper is the bazzite default and the
  obvious choice. btrbk has a nicer policy DSL and supports
  off-host send/receive. Defer to snapper for v1; revisit if the
  user wants off-host backup later.
- **Q2 — Firstboot wizard form factor**: TUI (default) keeps the
  image free of GUI dependencies and works in headless / SSH
  contexts. Alternatives: GTK dialog (nicer for users in GNOME);
  web wizard at `localhost:<port>` (nicest, but adds a web stack).
  Flag for user feedback once TUI ships.
- **Q3 — Cloud-key paste flow security**: even with masked stdin,
  the user typing or pasting a key in a terminal carries some
  exposure. Alternatives: prompt the user to drop the key into a
  pre-created file with `0600` perms and let the wizard read it
  (avoids terminal entirely). Worth revisiting once the SOPS
  flow has hardware testing.
