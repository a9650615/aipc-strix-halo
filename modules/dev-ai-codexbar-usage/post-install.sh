#!/bin/sh
set -eu

# Install the codexbar-usage Python package into the aipc venv.
# Build-time only: no systemctl --now, no health curls.
AIPC_VENV="/usr/lib/aipc/tools/.venv"
if [ ! -d "$AIPC_VENV" ]; then
    echo "dev-ai-codexbar-usage: aipc venv not found at $AIPC_VENV" >&2
    exit 1
fi

# After Containerfile COPY, package lives at /usr/lib/aipc-codexbar-usage/.
PKG_DIR=/usr/lib/aipc-codexbar-usage
if [ ! -d "$PKG_DIR" ]; then
    echo "dev-ai-codexbar-usage: package dir missing at $PKG_DIR" >&2
    exit 1
fi

PIP_BIN="$AIPC_VENV/bin/pip"
"$PIP_BIN" install --no-cache-dir "$PKG_DIR"

CLI_BIN="$AIPC_VENV/bin/aipc-usage"
if [ -f "$CLI_BIN" ] && [ ! -e /usr/bin/aipc-usage ]; then
    ln -sf "$CLI_BIN" /usr/bin/aipc-usage
    echo "dev-ai-codexbar-usage: symlinked aipc-usage -> /usr/bin/aipc-usage"
fi

# User unit is installed via files/usr/lib/systemd/user/aipc-usage.service.
# Enable at runtime (not here): systemctl --user enable --now aipc-usage.service
# GUI also auto-starts the server on demand via `aipc usage gui` / codexbar-gui.

echo "dev-ai-codexbar-usage: installed successfully"
