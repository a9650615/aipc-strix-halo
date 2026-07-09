#!/bin/sh
set -eu

# Install codexbar-gui into the aipc venv. Runs at image BUILD time — no
# user $HOME writes, no systemctl --now, no live service checks.

AIPC_VENV="/usr/lib/aipc/tools/.venv"
if [ ! -d "$AIPC_VENV" ]; then
    echo "dev-ai-codexbar-gui: aipc venv not found at $AIPC_VENV" >&2
    exit 1
fi

# After Containerfile COPY, package lives under /usr/lib/codexbar-gui.
PIP_BIN="$AIPC_VENV/bin/pip"
if [ -d /usr/lib/codexbar-gui ]; then
    GUI_SRC_DIR=/usr/lib/codexbar-gui
else
    # Dev / ansible script context (repo tree).
    GUI_SRC_DIR="$(cd "$(dirname "$0")" && pwd)/files/usr/lib/codexbar-gui"
fi

"$PIP_BIN" install --no-cache-dir "$GUI_SRC_DIR"

GUI_BIN="$AIPC_VENV/bin/codexbar-gui"
if [ -f "$GUI_BIN" ] && [ ! -e /usr/bin/codexbar-gui ]; then
    ln -sf "$GUI_BIN" /usr/bin/codexbar-gui
    echo "dev-ai-codexbar-gui: symlinked codexbar-gui -> /usr/bin/codexbar-gui"
fi

# System-wide desktop entry (application menu). User autostart is optional
# and belongs in first-login / docs — not image build against $HOME.
if [ -f /usr/lib/codexbar-gui/codexbar-gui.desktop ]; then
    mkdir -p /usr/share/applications
    cp -f /usr/lib/codexbar-gui/codexbar-gui.desktop /usr/share/applications/codexbar-gui.desktop
    echo "dev-ai-codexbar-gui: installed /usr/share/applications/codexbar-gui.desktop"
fi

# XDG autostart for all users (read-only image path).
if [ -f /usr/lib/codexbar-gui/autostart/codexbar-gui.desktop ]; then
    mkdir -p /etc/xdg/autostart
    cp -f /usr/lib/codexbar-gui/autostart/codexbar-gui.desktop /etc/xdg/autostart/codexbar-gui.desktop
    echo "dev-ai-codexbar-gui: installed /etc/xdg/autostart/codexbar-gui.desktop"
fi

echo "dev-ai-codexbar-gui: installed successfully"
