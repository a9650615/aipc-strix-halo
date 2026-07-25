# CodexBar GUI (Linux tray shell)

**Scope: GUI only.**

Core usage/OAuth/provider logic is **not** reimplemented here. This module is a
PySide6 system-tray front-end on top of the official Linux CLI:

- [steipete/CodexBar](https://github.com/steipete/CodexBar) → `codexbar` binary
- `codexbar usage --format json`
- `codexbar serve` → `GET /usage` / `/health`

```
┌─────────────┐     JSON      ┌──────────────────────┐
│ codexbar-gui│ ────────────► │ official codexbar    │
│ (this repo) │ ◄──────────── │ CLI / serve          │
└─────────────┘               └──────────────────────┘
```

Do **not** route this GUI through `aipc-usage` Python fetchers.

## Requirements

1. Official Linux CLI on `PATH` (or `~/.local/bin/codexbar` / `CODEXBAR_BIN`)
2. PySide6 (`python3-pyside6` or pip)
3. A desktop with a system tray (KDE Plasma works out of the box)

## Install official CLI

```sh
# Example: tarball from GitHub Releases (linux-x86_64 / aarch64 / musl)
# https://github.com/steipete/CodexBar/releases
install -m 755 CodexBarCLI ~/.local/bin/codexbar
codexbar --version
```

Configure providers the same way as upstream (CLI config under
`~/.config/codexbar/` — see upstream docs).

## Run

```sh
codexbar-gui
```

On start you get:

| Surface | What |
|---------|------|
| **Tray icon** | Remaining % digits + bottom bar (HiDPI; not an empty meter) |
| **Click tray** | Popover with **big remaining %** header + Session/Weekly cards |
| **Web UI** | `http://127.0.0.1:8080/` — HTML + Hermes-compatible `/usage` JSON |

**Port map:**

| Port | Role |
|------|------|
| **8080** | CodexBar GUI web (`codexbar-gui-web.service`) — HTML UI + `/usage` + `/health` (replaces `aipc-usage`) |

```sh
# Headless usage server (replaces aipc-usage):
systemctl --user enable --now codexbar-gui-web.service
# open http://127.0.0.1:8080/

# Tray + optional second web bind (reuses :8080 if already up)
codexbar-gui

# Web only
python3 -m codexbar_gui --web-only --web-port 8080
```

Data path is always official:

```sh
# GUI defaults to --provider codex (full “all providers” can hang on Claude/etc.)
codexbar usage --format json --provider codex --web-timeout 15
# optional: all providers (may hang)
export CODEXBAR_ALL_PROVIDERS=1
# or: export CODEXBAR_PROVIDER=claude
```

## What the menu shows (upstream fields)

- Session (5h) + Weekly **% left** bars
- Pace summary when present
- Account / plan / credits
- Real CLI error strings (e.g. Claude parse failures)

## Layout

```
codexbar_gui/
├── tray_app.py          # QSystemTrayIcon lifecycle
├── usage_panel.py       # Provider cards
├── upstream.py          # Parse official JSON only
├── server_launcher.py   # codexbar serve only
├── icon_updater.py      # Painted tray meter
├── claude_oauth.py      # Claude session token bridge for the CLI
├── kwin_place.py        # KDE Wayland popover docking
└── config_dialog.py     # Thin settings (shared config file path)
```

## Claude session token (ccs bridge)

The official CLI reads Claude credentials from `~/.claude/.credentials.json`
only — `CLAUDE_CONFIG_DIR` does not redirect it. `ccs` keeps the live tokens in
`~/.ccs/instances/<name>/.credentials.json` and leaves the shared file blank, so
`--source oauth` reported *"Claude OAuth access token missing"* on every poll
while Claude Code was logged in.

`claude_oauth.py` picks the freshest credential file, refreshes an expired
access token against the official endpoint, writes the rotated pair back (Claude
Code's own login would break otherwise), and hands the token to the CLI as
`CODEXBAR_CLAUDE_OAUTH_TOKEN`. Refresh failures back off for 5 minutes and the
stale token is still passed through — the API decides, not our clock.

Overrides: `CODEXBAR_CLAUDE_OAUTH_TOKEN` (skip the bridge entirely),
`CODEXBAR_CLAUDE_OAUTH_CLIENT_ID`, `CODEXBAR_CLAUDE_TOKEN_URL`.

## Popover placement on KDE Wayland

KWin drops client-set positions for `xdg_toplevel` surfaces: `move()` /
`QWindow.setPosition()` are ignored, Qt keeps reporting the *requested* rect, and
the popover actually lands wherever KWin placed it (screen centre). Qt's
`availableGeometry()` equals the full screen there, and `_NET_WORKAREA` is
XWayland-only, device-pixel scaled and unioned across outputs — on this machine
it claimed a 351 px top panel.

`kwin_place.py` therefore asks KWin itself: load a KWin script over D-Bus, read
`workspace.clientArea(PlacementArea)` for the output under the tray icon (the
only panel-aware work area on Wayland), and set `frameGeometry`. The window is
matched by caption (`CodexBar Usage Popover`).

The script is armed *before* `show()` and docks from `workspace.windowAdded`, not
after the map: placing later is visible as a jump from screen centre, and a
geometry change after KWin granted activation silently drops that activation.
(`QWidget.setWindowOpacity` cannot be used to hide the first frame — measured to
be a no-op on Wayland.)

Multi-monitor: the output comes from the tray icon rect, so the card docks on the
screen that owns the panel — never on the primary one by default. Plasma usually
reports **no** icon rect over SNI; then `anchor_real=False` and KWin looks up the
largest `dock` window on the active output and derives the anchor from its
geometry (right end for a horizontal panel, bottom end for a vertical one).
Hardware-verified on DP-1 `0,0 2560x1440` + eDP-1 `2560,204 1707x1067`: top tray
on either screen, bottom-edge panel (card grows upward), and the panel-derived
fallback all land inside the correct output's work area.

## Auto-dismiss

A Qt client on Wayland cannot decide this for itself:

- **activation lies.** KWin grants it ~300 ms after the map, hands it back to
  whatever was active before (measured: browser reclaims focus ~1.2 s after open),
  then re-activates the always-on-top card when that window closes. Sometimes it
  is never granted, so no `ActivationChange` ever fires and the card stays open
  forever — the original "unfocus 不一定會關".
- **the pointer is invisible.** `QCursor.pos()` freezes at the last position our
  own surface saw, and `underMouse()` stays false for a card that maps *under* a
  stationary pointer (no enter event) — measured.
- **a click on the already-focused window raises no signal at all.**

So on Wayland KWin decides, polled every 400 ms from `_dismiss_tick` via
`kwin_place.poll_dismiss()` — it reads `workspace.cursorPos` and
`workspace.activeWindow` and closes the window itself:

| Cursor (KWin) | Focus (KWin) | Result |
|---|---|---|
| on the card, its tray icon, or within `CURSOR_PAD` (32 px) of either | anything | stays — the user is right there |
| elsewhere | another window | closes within one tick |
| elsewhere | still ours | closes at `UNTOUCHED_CAP_S` (12 s) |

Plus, on any platform: Esc, the close button, a press outside inside our own
window tree, and clicking the tray icon again (`is_really_visible()` toggle, with
`hidden_within()` so the click that dismissed us does not bounce it back open).
Every Python-side dismissal logs its reason (`popover dismiss: …`).

`CODEXBAR_KWIN_DEBUG=1` makes the poll report its inputs over D-Bus, since KWin's
`print()` does not reach the journal here:

```sh
busctl --user monitor --match "interface='io.aipc.CodexbarProbe'"
# poll cursor=2346,300 card=2136,34 420x480 anchor=2531,0 24x24 engaged=true …
```

X11 keeps the client-side rules (`ACTIVATION_SETTLE`, `POINTER_LEAVE_GRACE`,
`UNTOUCHED_TIMEOUT`), where `QCursor.pos()` and activation are trustworthy.

## Tray shell (compatibility layer)

`codexbar_gui/shell_adapter.py` hosts the **same** `UsagePopover`:

| Mode | Default | Behavior |
|------|---------|----------|
| `window` | **yes** | Free top-level `show_at_tray`; docks top-right when SNI click is (0,0) |
| `sni_menu` | opt-in | Right-click small menu; left-click still uses window (full UI cannot use Wayland `QMenu.popup`) |

Override: `CODEXBAR_TRAY_SHELL=window|sni_menu`.

## Out of scope

- Reimplementing providers, OAuth, cookies, pace math
- Python `dev-ai-codexbar-usage` as the GUI data plane
- macOS menu-bar pixel parity (Merge Icons, widgets, Sparkle)
- Full Plasma plasmoid rewrite (optional later; thin shell first)

## Tests

```sh
QT_QPA_PLATFORM=offscreen \
PYTHONPATH=modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui \
  python3 -m pytest modules/dev-ai-codexbar-gui/tests/ -q
```
