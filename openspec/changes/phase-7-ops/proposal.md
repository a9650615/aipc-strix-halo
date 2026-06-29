## Why

Phases 0–6 build features; Phase 7 makes them reliable enough to live
with. A user who installs the AI PC should be able to break it (a
botched config edit, a model swap that misbehaves, a bad image
update), notice the breakage via one command (`aipc doctor`), and
roll back to a known-good state with a second command (`aipc
restore`). They should also be able to walk away for three months,
come back, and find the box still patched without having ceded
control of *when* the patch applied.

The architecture decision is that ops is **opinionated about
mechanism, never about taking actions for the user**: snapper does
the snapshots, doctor reads the truth, the firstboot wizard onboards,
the update timer notifies — but no system change ever ships without
the user typing the command. No auto-apply, no telemetry, no
"helpfully" rebooting.

## What Changes

- **New capability `ops`** covering the 3 Phase 7 modules as one
  coherent ops surface.
- **Snapper-driven BTRFS snapshots**: timeline (7d hourly / 4w
  weekly / 3m monthly) covering `/`, `/var`, `/home`, plus a
  pre-update hook that fires before every `bootc switch`.
- **Aggregated `aipc doctor`**: extends the existing doctor with
  GPU (rocm-smi), NPU (xdna-smi), and systemd is-active rolls for
  the core services (ollama, litellm, postgres, mem0, pipecat,
  agent).
- **Three-screen firstboot wizard**: persona, editor confirm, cloud
  API keys. Owned by `ops-firstboot` (the wizard runner); Phase 2
  and Phase 3 contribute additional screens (consent prompts and
  voice/wake-word capture) that plug into the same runner.
- **Weekly image-update check + user-consent apply**: an
  `aipc-update.timer` polls the tracked tag once a week; new digest
  available → desktop notification → user runs `aipc update` →
  `bootc switch` happens → reboot when the user chooses.
- **Dual update channels**: `:stable` (default, conservative) and
  `:rolling` (opt-in, fast-track). Tag recorded in
  `/etc/aipc/branding.env`.
- **No telemetry**: zero outbound network traffic from ops modules.
  Local logs only; any future exfil is explicit opt-in.
- **Restore CLI (`aipc restore`)**: lists snapper snapshots with
  timestamp / label / size; `aipc restore <id>` rolls back the
  selected subvols.

## Capabilities

### New Capabilities

- `ops`: Host-side ops surface — snapper-managed BTRFS snapshots,
  aggregated doctor (verify.sh + GPU + NPU + services), firstboot
  wizard runner, weekly update check with user-consent apply, dual
  update channels, no-telemetry stance, restore CLI. Provides the
  hosting for Phase 2 and Phase 3 wizard-screen contributions.

### Modified Capabilities

- (none) Phase 7 is host-side ops; no existing capability's
  requirements change. Existing `aipc doctor` (from earlier phases)
  is extended with new sections, not redefined.

## Impact

- **`modules/`**: 3 new modules added (see tasks group 1). No
  existing module is touched.
- **`tools/aipc doctor`**: Extended with GPU, NPU, services, and
  ops-specific checks (snapshot policy, update channel, wizard
  completion state).
- **`tools/aipc`**: New top-level subcommands (`init`, `update`,
  `restore`, `snap`).
- **`targets/bootc/Containerfile` + `targets/ansible/site.yml`**:
  Rendered outputs grow by 3 modules; both targets must reach the
  same end state. bootc pre-switch hook script added.
- **First-boot user actions**: The wizard runs the first time the
  primary user logs in (or when `aipc init` is invoked). Captures
  persona (Phase 3 contributes the voice screens), editor
  (Phase 6's Zed default; user can switch), cloud API keys (SOPS
  encryption per `cloud-llm-fallback` change).
- **bootc tag tracking**: `/etc/aipc/branding.env` declares the
  active tag (`:stable` or `:rolling`).
- **Phase dependencies (soft)**: doctor checks for Phases 1–6
  services run as INFO when the corresponding phase isn't deployed
  (e.g., no Pipecat → INFO not FAIL).
