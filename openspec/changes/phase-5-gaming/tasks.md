## 1. Module Scaffolding (3 modules)

- [ ] 1.1 `gaming-base`: create `modules/gaming-base/` with README,
  packages.txt (steam, mangohud, gamescope, gamemode), files/ for
  gamescope GDM session unit + controller udev rules, post-install.sh
  (register gamescope session with GDM, ensure default session stays
  GNOME), verify.sh (steam binary present, mangohud present,
  gamescope session registered with GDM, default session is GNOME).
- [ ] 1.2 `gaming-ai-overlay`: create `modules/gaming-ai-overlay/`
  with README, packages.txt (gtk4 or equivalent for the daemon),
  files/ for the overlay daemon binary / script and the Super+G
  GNOME keybinding (also registered inside the gamescope session
  config), post-install.sh (register binding), verify.sh (binary
  present, keybinding registered).
- [ ] 1.3 `game-strategy-rag`: create `modules/game-strategy-rag/`
  with README, files/ for the ingest worker, the systemd timer, and
  the empty `/etc/aipc/game-strategy/sources.yaml`, verify.sh
  (registry file exists, worker unit loadable).

## 2. gamescope Session

- [ ] 2.1 Drop the gamescope `.desktop` session entry under
  `/usr/share/wayland-sessions/` so GDM picks it up.
- [ ] 2.2 Confirm default session stays GNOME on a freshly-deployed
  image (no user account default override).
- [ ] 2.3 Document the GDM session-picker entry in `gaming-base/README.md`.

## 3. Steam + MangoHud

- [ ] 3.1 Steam installed via rpm-ostree layer (bazzite-dx already
  provides the package; confirm presence and pin if needed).
- [ ] 3.2 MangoHud installed and enabled per-game via Steam launch
  options or the gamescope env (`MANGOHUD=1`).
- [ ] 3.3 Controller udev rules drop into
  `/etc/udev/rules.d/` so common gamepads work without manual
  `modprobe`.

## 4. Heroic Opt-In Helper

- [ ] 4.1 `tools/aipc gaming install-heroic`: runs `flatpak install
  -y flathub com.heroicgameslauncher.hgl`, idempotent.
- [ ] 4.2 Helper documented in `gaming-base/README.md`.

## 5. Overlay Daemon + Strategy-RAG CLI

- [ ] 5.1 Overlay daemon: small process subscribing to the agent's
  /chat or Daily Assistant reply stream; renders the reply text in a
  gamescope overlay surface; toggled by `Super+G`.
- [ ] 5.2 `aipc gaming enable-overlay [--force]` and `disable-overlay`
  verbs.
- [ ] 5.3 `aipc gaming strategy-rag add/list/remove` verbs +
  `aipc gaming strategy-rag reindex <game>`.
- [ ] 5.4 Ingest worker: timer-driven, reads
  `/etc/aipc/game-strategy/sources.yaml`, single-URL crawl with
  depth limit for v1 (Q3 — RSS / sitemap deferred); embeds via the
  Phase 2 `embed-bge` alias; writes vectors tagged with the game
  name.

## 6. Voice Pipeline Gaming-Mode Adjustments

- [ ] 6.1 `voice-pipecat.service` drop-in
  (`/etc/systemd/system/aipc-voice-pipecat.service.d/gaming.conf`)
  sets `Nice=5` and `IOSchedulingClass=best-effort` while gamescope
  is active. Drop-in activated by a small DBus watcher that toggles
  the override based on the active session.
- [ ] 6.2 Confirm NPU wake-word path is untouched (no iGPU contention
  from wake inference).
- [ ] 6.3 Document the gaming-mode tweak in `gaming-base/README.md`.

## 7. Anti-Cheat Detection For Overlay

- [ ] 7.1 Detection helper: read Steam title metadata (`appmanifest`
  or Steam Web API offline cache); set an AC flag.
- [ ] 7.2 Overlay daemon checks the flag at launch and stays
  inactive when set.
- [ ] 7.3 `/etc/aipc/game-strategy/overlay-overrides.yaml` records
  per-title overrides.
- [ ] 7.4 (Q1) Document tested AC engines and known-safe vs
  known-flagged titles in `gaming-ai-overlay/README.md`.

## 8. Doctor Checks

- [ ] 8.1 `aipc doctor` gaming section asserts:
  - Steam binary present.
  - MangoHud present.
  - gamescope session registered with GDM.
  - Controller subsystem reachable (`/dev/input/by-id/`).
- [ ] 8.2 INFO (not FAIL) checks:
  - Heroic install status (with hint to run `aipc gaming
    install-heroic`).
  - Strategy-RAG ingest status (per-game last-cycle timestamp).
  - VRR / HDR support flag (Q2 — documented INFO until verified).
- [ ] 8.3 When in gamescope session, additionally assert:
  - Voice pipeline alive.
  - Scheduler niceness ≥ 5 on `voice-pipecat`.

## 9. Documentation

- [ ] 9.1 Per-module README for each of the 3 modules.
- [ ] 9.2 `docs/gaming.md`: session-switching, overlay binding, AC
  policy, strategy-RAG workflow, VRR / HDR caveats.
- [ ] 9.3 Confirm `docs/architecture.md §7` Phase 5 row matches the
  3-module list shipped here (no count change to the §7 header
  total).

## 10. Local Build Verification

- [ ] 10.1 Run `tools/aipc render bootc`; confirm Containerfile
  includes all 3 gaming modules.
- [ ] 10.2 Run `tools/aipc render ansible --check`; confirm it
  lints clean.
- [ ] 10.3 Run each module's `verify.sh` in a privileged container.

## 11. AI PC Hardware Verification

- [ ] 11.1 Deploy `:rolling` tag to the AI PC via `bootc switch`.
- [ ] 11.2 Confirm `Gamescope` appears in GDM session list; default
  is still GNOME.
- [ ] 11.3 Log in to gamescope; confirm Steam launches and a known
  controller is detected.
- [ ] 11.4 Launch a single-player title; trigger the overlay with
  Super+G; trigger voice with the wake word; confirm both work.
- [ ] 11.5 Launch an AC-flagged title; confirm overlay stays
  disabled by default; override with `aipc gaming enable-overlay
  --force`; relaunch; confirm overlay active.
- [ ] 11.6 `aipc gaming strategy-rag add elden-ring <url>`; wait for
  the next ingest cycle; confirm vectors land in the Phase 2
  backend tagged with `elden-ring`.
- [ ] 11.7 Run `aipc gaming install-heroic`; confirm Heroic shows up
  in the apps grid.

## 12. Archive Change

- [ ] 12.1 Run `npx -y @fission-ai/openspec validate phase-5-gaming
  --strict` — must print `Change 'phase-5-gaming' is valid`.
- [ ] 12.2 Run `npx -y @fission-ai/openspec archive phase-5-gaming`
  to merge the spec into `openspec/specs/gaming/spec.md` and close
  the change.
