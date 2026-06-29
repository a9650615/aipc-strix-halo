## Why

Bazzite-dx already gives the user a competent gaming substrate (Steam,
Proton, controllers, MangoHud, gamescope). Phase 5 doesn't compete with
that — it bolts the AI PC's voice and overlay surfaces onto it so the
assistant stays useful *during* games, and ships a strategy-RAG
framework the user fills in per game (the image itself stays
opinion-free on game guides, licenses, and source URLs).

The architecture decision is that gaming mode is **opt-in via the GDM
session picker**, not a default. The image boots into GNOME by default
so the dev workflow stays the primary experience; the user enters the
gamescope session when they want a console feel. The voice pipeline
(Phase 3) and Phase 4 agent runtime both survive the switch.

## What Changes

- **New capability `gaming`** covering the 3 Phase 5 modules as one
  coherent gaming surface.
- **gamescope session installed, not default**: the image registers
  the gamescope session with GDM so it shows in the session picker;
  default desktop stays GNOME.
- **Steam preinstalled as RPM-OSTree layer**: native install, not
  Flatpak (Proton compatibility is materially better).
- **Heroic Games Launcher opt-in**: shipped as an `aipc gaming
  install-heroic` helper that installs the Flatpak on demand.
- **In-game AI triggers run in parallel**: voice (wake word stays on
  via Phase 3) and a floating overlay (Super+G toggle) covering the
  hands-busy vs visual-reference axes.
- **Strategy-RAG framework with empty registry**: the
  `game-strategy-rag` module ships the ingest pipeline + CLI but no
  baked sources. The user declares per-game sources at runtime.
- **Voice pipeline survives gaming mode**: when gamescope session is
  active, Pipecat lowers compute priority but keeps the NPU
  wake-word path live.

## Capabilities

### New Capabilities

- `gaming`: Host-side gaming surface — gamescope session
  (registered, not default), Steam (RPM-OSTree native + MangoHud),
  Heroic (opt-in), in-game voice + overlay triggers, strategy-RAG
  framework (no sources baked), voice-pipeline gaming-mode
  adjustments. Reuses Phase 3 voice and Phase 4 agent runtime; adds
  no new LLM aliases.

### Modified Capabilities

- `voice` (Phase 3): No requirement changes. Phase 5 declares
  gaming-mode behaviour for the existing voice pipeline (lower
  scheduler priority, NPU stays on).
- `memory-rag` (Phase 2): No requirement changes. Strategy-RAG
  consumes the existing embedder + vector backend; it adds source
  declarations, not infrastructure.

## Impact

- **`modules/`**: 3 new modules added (see tasks group 1). No
  existing module is touched.
- **`tools/aipc doctor`**: Gains a `gaming` section asserting Steam
  installed, controllers detected (when plugged), MangoHud present,
  voice pipeline alive in gamescope session.
- **`tools/aipc gaming`**: New top-level subcommand
  (`install-heroic`, `enable-overlay`, `disable-overlay`,
  `strategy-rag add/list/remove`).
- **`tools/aipc game-strategy`**: Alias for the strategy-RAG verbs
  if needed; consolidated under `aipc gaming` to keep CLI shallow.
- **`targets/bootc/Containerfile` + `targets/ansible/site.yml`**:
  Rendered outputs grow by 3 modules; both targets must reach the
  same end state.
- **GDM session list**: Gains a `gamescope` entry.
- **Phase 3 dependency**: in-game voice needs Phase 3 deployed.
  Phase 5 hardware verification gates on Phase 3 being live.
- **Phase 2 dependency (soft)**: strategy-RAG ingests via the
  Phase 2 embedder. Without Phase 2, the registry exists but
  ingest jobs fail with a clear status message.
