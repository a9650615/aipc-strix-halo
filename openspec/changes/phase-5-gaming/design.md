## Context

The AI PC is a developer workstation first. Gaming is the second-class
use case the hardware also supports (Strix Halo's iGPU is competent for
1080p–1440p AAA). The image already inherits bazzite-dx, which is the
right substrate; Phase 5's job is the AI-on-top:

1. Register the gamescope session for users who want a console feel,
   without forcing it on dev sessions.
2. Make the voice assistant work while a game is fullscreen (so the
   user can ask "where's the next boss" without alt-tab).
3. Render an opt-in overlay (subtitle box + hotkey toggle) that
   shows agent replies inside the game's compositor.
4. Provide a strategy-RAG framework — pipeline + CLI — without baking
   any sources. The user picks per-game URLs / feeds; license, ToS,
   and source quality are user-side choices.

The strategy-RAG decision matters: the user explicitly told us this
phase is framework-only — "可以 config 設定即可, 非現在必須". We
ship pipes; users fill them.

## Goals / Non-Goals

**Goals:**

- Boot the AI PC, pick `Gamescope` at GDM, drop into a console-shell
  game session with voice + overlay alive.
- The same voice wake word the user trained in Phase 3 keeps working
  inside the gamescope session.
- Strategy-RAG framework supports per-game source declarations
  (URL / RSS / sitemap) and ingests through the Phase 2 embedder.
- AI overlay defaults to disabled for multiplayer titles to avoid
  anti-cheat false positives (Q1).

**Non-Goals:**

- Baking specific game wikis or guides into the image. License /
  ToS / staleness all argue against bundling.
- A custom compositor or overlay engine. Reuse gamescope's overlay
  protocol (the same one MangoHud uses).
- Live web-scraping during gameplay. Strategy-RAG ingests on a
  schedule the user controls; gameplay queries hit the local
  vector store.
- Cloud game-save sync, friend-list import, parental controls.
  Bazzite ships what it ships; Phase 5 doesn't change defaults.
- VR. v2 at earliest; needs separate hardware and stack work.

## Decisions

**D1 — gamescope session installed, not default-entered**

*Chosen:* The image ships the gamescope session unit registered with
GDM. Default-session stays GNOME. User picks `Gamescope` at the GDM
session selector when they want it.

*Alternatives:*
- Default-enter gamescope: kills the dev workflow.
- Don't ship: loses the console feel that the hardware supports.

*Why chosen:* Dev is the primary workflow. Gamescope is one click
away when wanted; never in the way when not.

**D2 — Steam primary, Heroic opt-in via helper**

*Chosen:* Steam ships native (RPM-OSTree layer) plus MangoHud.
Heroic Games Launcher is not in the image; `aipc gaming
install-heroic` installs the Flatpak when the user asks.

*Alternatives:*
- Lutris + Bottles: powerful but overkill for the target audience.
- Steam-only: skips free Epic releases.
- Heroic baked: extra ~200 MiB and a Flatpak dependency for users
  who never touch Epic / GOG.

*Why chosen:* Steam covers ~80% of cases; Heroic adds the rest with
zero image-build cost (Flatpak install on demand).

**D3 — In-game AI: voice + overlay, both shipped active**

*Chosen:* Two parallel triggers. The voice pipeline (Phase 3) keeps
running in the gamescope session (NPU wake word always on, STT/TTS
on demand). An overlay daemon registers a `Super+G` toggle that
shows / hides a subtitle box rendered through gamescope's overlay
surface.

*Alternatives:*
- Voice-only: breaks in multiplayer voice chat or noisy headphones.
- Overlay-only: kills the hands-busy pitch.
- Trigger via Steam Input gesture: nice but tied to a controller.

*Why chosen:* The two channels cover complementary scenarios; both
are cheap to ship since the underlying voice pipeline already
exists.

**D4 — Strategy-RAG: framework + config slots, no sources baked**

*Chosen:* `game-strategy-rag` ships an empty registry at
`/etc/aipc/game-strategy/sources.yaml`. The user declares per-game
entries (URL / RSS / sitemap + cadence). The module ships the
ingest worker, the CLI verbs, and the doctor checks; it ships no
opinions on which games or sources.

*Alternatives:*
- Bake CN-wiki / Reddit-CN / 巴哈姆特 / Fextralife: gets stale,
  license-fuzzy, gives the impression the project endorses the
  source.
- Live web-scrape: compute waste, fragile against ToS / rate
  limits.

*Why chosen:* User explicit. The framework is the value; sources
are user-side and per-game.

**D5 — In-game voice processing: same Pipecat, gaming-mode scheduler tweak**

*Chosen:* When the gamescope session is active, `voice-pipecat`
lowers its scheduler priority (`nice` + `IOSchedulingClass=best-effort`)
so the GPU contention with the game stays minimal. The NPU
wake-word path is unchanged (it doesn't touch the iGPU). STT runs
on the iGPU only after wake, so its cost is bounded.

*Alternatives:*
- Separate gaming-voice service: duplicates Phase 3.
- Suspend the voice pipeline entirely during games: kills the
  signature feature.

*Why chosen:* One source of truth for voice; the gaming-mode tweak
is a few env-file lines, not a rewrite.

**D6 — Overlay rendering: reuse gamescope's overlay protocol**

*Chosen:* The overlay daemon uses gamescope's existing overlay
surface (same mechanism MangoHud uses). The daemon renders a
single subtitle / dialogue box plus its toggle binding.

*Alternatives:*
- Separate compositor hack: fragile against gamescope updates.
- Steam in-game overlay: tied to Steam; doesn't render in
  non-Steam games.

*Why chosen:* Matches the platform; no parallel compositor to
maintain; works in any gamescope-launched title.

## Risks / Trade-offs

- **Anti-cheat false-positive on the overlay**: some online games'
  anti-cheat (EAC, BattlEye) flag DLL / compositor hooks. The
  gamescope overlay is comparatively safe (kernel-level
  anti-cheats see a normal compositor), but multiplayer titles
  are still risky. **Mitigation (Q1)**: default the overlay to
  disabled when launching a Steam title that declares an
  anti-cheat flag; the user can override with `aipc gaming
  enable-overlay --force`.
- **VRR / HDR on gfx1151**: Strix Halo + gamescope VRR/HDR is
  newer than the AI PC's other paths. **Mitigation (Q2)**:
  document required kernel / Mesa versions; doctor reports
  status; ship the session unit conservatively (60 Hz fixed)
  with VRR opt-in.
- **Microphone privacy during multiplayer**: leaving the wake
  word on in-game means the assistant might trigger from
  squadmates' voice chat. **Mitigation**: `aipc-voice-mute.target`
  (Phase 3) covers this — a `mute` voice command or GNOME DND
  pauses the wake word; the user can also bind a gamescope-side
  hotkey to toggle it.
- **Strategy-RAG source format ambiguity (Q3)**: URL / RSS /
  sitemap each need slightly different ingest logic. **Mitigation**:
  v1 supports URL (single-shot crawl with a depth limit). RSS
  and sitemap are v2 follow-ups; the YAML schema is
  forward-compatible (`type: url|rss|sitemap`).
- **Steam credential prompt during firstboot**: Steam wants an
  account. Image cannot bake credentials. **Mitigation**: same
  pattern as Claude Code (Phase 6): ship the binary, user logs
  in on first launch; doctor reports INFO when not logged in.

## Migration Plan

No prior gaming surface exists on this image. Phase 5 is net-new.
Two ordering concerns:

1. Phase 3 must be deployed before Phase 5 for the in-game voice
   triggers to be meaningful. Phase 5 ships happily without Phase
   3 — the overlay still works — but voice triggers are no-ops.
2. Phase 2 must be deployed before strategy-RAG can index anything.
   Without Phase 2, the registry exists, the CLI verbs work, but
   ingest jobs error with a clear "memory-rag not available"
   message.

The `Gamescope` session entry shows up at GDM after the first
reboot following image apply. Users who never pick it pay nothing
beyond the disk footprint (~300 MiB for Steam + ~50 MiB for
overlay + RAG framework).

## Open Questions

- **Q1 — Anti-cheat overlay safety**: which AC engines flag the
  gamescope overlay vs ignore it? Needs per-title testing. Default
  to disabled for AC-flagged titles; expose override.
- **Q2 — VRR / HDR baseline on gfx1151**: which Mesa + kernel
  combinations enable working VRR and HDR through gamescope on
  Strix Halo? Documented as INFO in doctor until tested.
- **Q3 — Strategy-RAG source schema v2**: RSS and sitemap support,
  per-source rate limits, robots.txt respect. v1 ships
  single-URL crawl with depth limit; schema is forward-compatible.
