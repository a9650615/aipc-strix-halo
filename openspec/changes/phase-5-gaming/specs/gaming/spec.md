## ADDED Requirements

### Requirement: gamescope Session Installed, Not Default-Entered

The `gaming-base` module SHALL register the gamescope session with
GDM so it appears in the session selector. The default GDM session
SHALL remain GNOME. No image-build step SHALL set gamescope as the
primary session. Switching is a per-login choice via the GDM
session picker.

#### Scenario: Gamescope appears in GDM session list

- **WHEN** the image is freshly deployed and GDM is queried for its
  registered sessions
- **THEN** the list includes a `gamescope` entry alongside the
  default `gnome` entry

#### Scenario: Default session remains GNOME

- **WHEN** the image is freshly deployed
- **THEN** the user account's default session (recorded in
  `~/.cache/gdm/last-session` after a first GNOME login, or the
  system default for fresh accounts) is `gnome`, not `gamescope`

---

### Requirement: Steam Installed Natively (RPM-OSTree Layer)

The `gaming-base` module SHALL install Steam as an RPM-OSTree layer
(not as a Flatpak). MangoHud SHALL be installed in the same module.
Controllers exposed via `udev` rules SHALL be detectable without
manual `modprobe` after a clean boot.

#### Scenario: Steam resolves natively

- **WHEN** the image is freshly deployed
- **THEN** `which steam` returns a path under `/usr` (not under
  `/var/lib/flatpak`) and `steam --version` runs without error

#### Scenario: MangoHud installed

- **WHEN** the image is freshly deployed
- **THEN** `which mangohud` returns a path under `/usr`

#### Scenario: Controller detection works after boot

- **WHEN** a known controller is connected on a fresh boot (no
  manual driver load)
- **THEN** `ls /dev/input/by-id/` lists the controller node and
  Steam's controller settings page sees the device

---

### Requirement: Heroic Games Launcher Opt-In Helper

The `gaming-base` module SHALL ship an `aipc gaming install-heroic`
helper that installs Heroic Games Launcher as a Flatpak on demand.
Heroic SHALL NOT be installed in the base image. The helper SHALL be
idempotent and SHALL print a clear status when Heroic is already
installed.

#### Scenario: Heroic absent on fresh image

- **WHEN** the image is freshly deployed
- **THEN** `flatpak list | grep -i heroic` exits non-zero (Heroic
  not installed)

#### Scenario: Helper installs Heroic on demand

- **WHEN** the user runs `aipc gaming install-heroic`
- **THEN** Heroic is installed via Flatpak and appears in the GNOME
  applications grid; running the helper a second time prints
  "already installed" and exits 0

---

### Requirement: In-Game AI Triggers — Voice And Overlay Both Active

The `gaming-ai-overlay` module SHALL ship a floating subtitle / reply
overlay rendered through gamescope's overlay surface, toggleable by
`Super+G`. The voice pipeline (Phase 3) SHALL stay active inside the
gamescope session so the user's wake word continues to work. Both
trigger paths SHALL be operable in parallel without conflict.

#### Scenario: Overlay toggle binding registered

- **WHEN** the image is freshly deployed and the user enters the
  gamescope session
- **THEN** pressing `Super+G` shows the overlay; pressing it again
  hides it

#### Scenario: Voice wake word works in gamescope

- **WHEN** the user is in the gamescope session with the wake word
  trained (Phase 3) and a game running
- **THEN** speaking the wake word triggers the Pipecat pipeline (STT
  → /chat → TTS) without leaving the game session

---

### Requirement: Voice Pipeline Survives Gaming Mode

The `voice-pipecat` service (Phase 3) SHALL remain active when the
gamescope session is the active GDM session. Phase 5 SHALL apply a
gaming-mode scheduler adjustment: `voice-pipecat.service` SHALL run
at a lower scheduler priority (`Nice=5` or equivalent) and
`IOSchedulingClass=best-effort` while gamescope is active. The NPU
wake-word path SHALL NOT be affected by the gaming-mode adjustment.

#### Scenario: Pipecat alive in gamescope

- **WHEN** the user enters the gamescope session
- **THEN** `systemctl is-active aipc-voice-pipecat.service` returns
  `active`

#### Scenario: Scheduler tweak applied under gamescope

- **WHEN** gamescope is the active session
- **THEN** the `voice-pipecat` process's scheduler niceness is ≥ 5
  (lower priority than default)

#### Scenario: NPU wake-word path unaffected

- **WHEN** gamescope is the active session
- **THEN** `voice-wake.service` is active and the NPU shows the
  same low-power wake-word inference utilisation as in the GNOME
  session

---

### Requirement: Strategy-RAG Framework Ships With Empty Source Registry

The `game-strategy-rag` module SHALL ship the ingest pipeline, CLI
verbs, and a YAML registry file at
`/etc/aipc/game-strategy/sources.yaml` initialised empty (no entries
for any game). The user SHALL declare per-game sources via `aipc
gaming strategy-rag add <game> <source-url>`. The ingest worker
SHALL run on a schedule per the registry entries and SHALL embed
crawled content through the Phase 2 embedder.

#### Scenario: Registry empty on fresh image

- **WHEN** the image is freshly deployed
- **THEN** `/etc/aipc/game-strategy/sources.yaml` exists and
  `aipc gaming strategy-rag list` prints an empty list

#### Scenario: Adding a source populates the registry

- **WHEN** the user runs `aipc gaming strategy-rag add elden-ring
  https://example.org/elden-ring-wiki`
- **THEN** the registry file lists the entry and a scheduled
  ingest unit picks it up on the next cycle

#### Scenario: Ingest worker uses Phase 2 embedder

- **WHEN** the ingest worker processes a registered source and
  Phase 2 is deployed
- **THEN** the embedder request lands at LiteLLM's `embed-bge`
  alias and vectors land in the active vector backend

#### Scenario: Ingest reports clearly when Phase 2 absent

- **WHEN** the ingest worker runs and Phase 2 (`rag-embedder` or
  `db-postgres`) is not deployed
- **THEN** the worker exits non-zero with a stderr message naming
  the missing Phase 2 dependency, and `aipc doctor`'s gaming
  section reports INFO (not FAIL)

---

### Requirement: Overlay Defaults To Disabled For Anti-Cheat-Flagged Titles

The overlay daemon SHALL default to disabled when launching a Steam
title whose Steam metadata indicates the presence of EAC, BattlEye,
or a comparable kernel-level anti-cheat. The user SHALL be able to
override with `aipc gaming enable-overlay --force`. The override
SHALL be per-title and SHALL be recorded under
`/etc/aipc/game-strategy/overlay-overrides.yaml`.

#### Scenario: Anti-cheat detection disables overlay by default

- **WHEN** the user launches a Steam title whose metadata declares
  EAC or BattlEye
- **THEN** the overlay daemon stays inactive for that title and a
  notification names the reason

#### Scenario: Override enables overlay for one title

- **WHEN** the user runs `aipc gaming enable-overlay --force` for
  an AC-flagged title and re-launches it
- **THEN** the overlay becomes active for that title only; other
  AC-flagged titles remain default-disabled
