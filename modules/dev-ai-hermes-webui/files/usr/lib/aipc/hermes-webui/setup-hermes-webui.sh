#!/bin/sh
# setup-hermes-webui.sh — RUNTIME oneshot (first boot / pin change).
# Provisions the hermes-webui home checkout at a pinned ref, enables lingering
# so the user service runs at boot, and starts it. Idempotent + offline-safe.
set -eu

REPO="https://github.com/nesquena/hermes-webui.git"
PIN="exp-v0.52.39"
PIN_FILE="/var/lib/aipc/hermes-webui-setup.pin"

target_user="$(awk -F: '$3 >= 1000 && $3 < 60000 {print $1; exit}' /etc/passwd)"
if [ -z "$target_user" ]; then
    echo "hermes-webui-setup: no primary user found — skipping" >&2
    exit 0
fi
target_home="$(getent passwd "$target_user" | cut -d: -f6)"
target_uid="$(id -u "$target_user")"
dest="$target_home/.hermes/hermes-webui"

as_user() {
    runuser -u "$target_user" -- env \
        "HOME=$target_home" "XDG_RUNTIME_DIR=/run/user/${target_uid}" "$@"
}

# Fast path: pin already applied and checkout present → nothing to do.
if [ -f "$PIN_FILE" ] && [ "$(cat "$PIN_FILE" 2>/dev/null)" = "$PIN" ] \
    && [ -d "$dest/.git" ]; then
    exit 0
fi

# Linger so the user manager (and the auto-enabled user unit) start at boot
# without an interactive login. Persists across reboots.
loginctl enable-linger "$target_user" 2>/dev/null || true

mkdir -p "$target_home/.hermes"
chown "$target_user":"$target_user" "$target_home/.hermes" 2>/dev/null || true

if [ ! -d "$dest/.git" ]; then
    if ! as_user git clone --depth 1 --branch "$PIN" "$REPO" "$dest"; then
        echo "hermes-webui-setup: clone failed (offline?) — will retry next boot" >&2
        exit 0
    fi
else
    as_user git -C "$dest" fetch --depth 1 origin "$PIN" 2>/dev/null || true
    as_user git -C "$dest" checkout -q "FETCH_HEAD" 2>/dev/null \
        || as_user git -C "$dest" checkout -q "$PIN" 2>/dev/null || true
fi

# Start now (subsequent boots start via linger + the shipped auto-enable symlink).
as_user systemctl --user daemon-reload 2>/dev/null || true
as_user systemctl --user start hermes-webui.service 2>/dev/null || true

mkdir -p /var/lib/aipc
printf '%s\n' "$PIN" > "$PIN_FILE"
