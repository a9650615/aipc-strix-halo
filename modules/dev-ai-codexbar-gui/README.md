# CodexBar GUI — System Tray Application

A PySide6 (Qt6) system tray application for CodexBar, providing real-time
visualization of AI coding tool usage directly in your desktop's system tray.

Built for KDE/Plasma with StatusNotifier support, featuring dynamic SVG icons
that reflect usage levels at a glance.

## Features

- **System tray meter icon** (painted QPixmap — reliable on Plasma StatusNotifier):
  - Green (&lt;50%) / yellow (50–80%) / red (&gt;80%) / gray (no data)
  - Tooltip lists per-provider usage; icon uses **max** usage across providers
- **Context menu** (refreshes on every open):
  - Progress bars, % , reset text, status (`ok` / `no key` / `error` / …)
  - Sorted by urgency (high usage first)
  - **Show details** expands secondary windows / errors / identity
- **Left-click or double-click** opens the menu
- **Auto-start** `aipc-usage serve` if health check fails
- **Settings** dialog writes `~/.config/codexbar/config.json` (`apiKey` camelCase)
- Prefer `aipc usage gui` as the human entrypoint

## Architecture

```
codexbar_gui/
├── __init__.py            # Package root, version
├── __main__.py            # Entry point (codexbar-gui CLI)
├── tray_app.py            # Main app class (tray icon, server, timer)
├── usage_panel.py         # Right-click context menu (QMenu + ProviderRow)
├── icon_updater.py        # Dynamic SVG icon generator
├── config_dialog.py       # Settings dialog (providers, API keys, refresh)
└── server_launcher.py     # HTTP server detection and auto-start
```

## Data Flow

```
User clicks tray icon
    ↓
UsagePanel opens → fetches GET /usage from HTTP server
    ↓
Server responds with JSON array of provider snapshots
    ↓
ProviderRow widgets rendered in menu
    ↓
Tray icon updated (if usage changed significantly)
```

## Installation

Built as part of the `dev-ai-codexbar-gui` module in the aipc project.

```sh
# From the project root — builds the container image with the GUI module.
tools/aipc render bootc

# Or validate the ansible render.
tools/aipc render ansible --check
```

Once the image is running:

```sh
# Preferred aipc entrypoint
aipc usage gui

# Direct launchers
codexbar-gui &
python -m codexbar_gui
```

## Usage

```sh
# Start the application (runs in background).
aipc usage gui
# or: codexbar-gui

# The app auto-starts the HTTP server on port 8080 if not running.
# Right-click the tray icon to see usage data.
# Double-click the tray icon to open the menu.
# Right-click → Settings to configure providers.

# Optional: keep the HTTP server as a user service
systemctl --user enable --now aipc-usage.service
```

## Configuration

Two configuration locations:

1. **Module defaults** — `files/etc/aipc/codexbar-gui/config.yaml` (module-level)
2. **User config** — `~/.config/codexbar/config.json` (shared with `aipc-usage`)

The user config manages provider enable/disable and API keys. The module config
controls server host/port and refresh interval.

## Dependencies

- **PySide6** (Qt6) — installed via `packages.txt`
- **codexbar-usage** — HTTP server (`aipc-usage serve`)
- **X11/Wayland** — system tray integration

## Verification

```sh
# Run the module verification script.
./verify.sh
```

## Module Integration

- **Bootc**: `Containerfile` COPY + `post-install.sh` pip-installs into the
  aipc venv. PySide6 is installed via `packages.txt` (system packages).
- **Ansible**: `modules/dev-ai-codexbar-gui/` is referenced from the playbook;
  renders identically to the bootc target.
- **Verify**: `verify.sh` checks the package is importable and all modules load.

## Linux Support

- **KDE Plasma**: Full support via StatusNotifier (native system tray)
- **GNOME**: Partial support via statusNotifierItem extension
- **X11**: Full support via XEmbed system tray
- **Wayland**: Requires StatusNotifier protocol (Plasma) or extension

## See Also

- `modules/dev-ai-codexbar-usage/` — the HTTP server and provider registry
- [CodexBar](https://github.com/steipete/CodexBar) — original Swift implementation

