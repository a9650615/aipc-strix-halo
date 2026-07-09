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
| **Web UI** | `http://127.0.0.1:8787/` — **this** is the HTML UI |

**Port map (do not confuse):**

| Port | Role |
|------|------|
| **8787** | CodexBar GUI web dashboard (HTML) — open this in browser |
| **8080** | Official `codexbar serve` JSON only — `GET /` is 404 by design |
| 8000 | Unused |

```sh
# Restart after pulling (old process has no web / old icon):
pkill -f 'python3 -m codexbar_gui' || true
codexbar-gui
# open http://127.0.0.1:8787/

# Web only (no tray)
python3 -m codexbar_gui --web-only --web-port 8787
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
└── config_dialog.py     # Thin settings (shared config file path)
```

## Out of scope

- Reimplementing providers, OAuth, cookies, pace math
- Python `dev-ai-codexbar-usage` as the GUI data plane
- macOS menu-bar pixel parity (Merge Icons, widgets, Sparkle)

## Tests

```sh
QT_QPA_PLATFORM=offscreen \
PYTHONPATH=modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui \
  python3 -m pytest modules/dev-ai-codexbar-gui/tests/ -q
```
