#!/bin/sh
# verify.sh — dev-ai-hermes-webui
# exit 0 = pass, 2 = optional/not-yet-provisioned, other = fail.
set -eu

fail() { echo "dev-ai-hermes-webui: $1" >&2; exit 1; }

UNIT=/usr/lib/systemd/user/hermes-webui.service
WANTS=/usr/lib/systemd/user/default.target.wants/hermes-webui.service
SETUP=/usr/lib/aipc/hermes-webui/setup-hermes-webui.sh
ONESHOT=/etc/systemd/system/aipc-hermes-webui-setup.service
CARD=/etc/aipc/portal/services/hermes-webui.yaml

[ -f "$UNIT" ]    || fail "user unit missing: $UNIT"
[ -L "$WANTS" ] || [ -f "$WANTS" ] || fail "auto-enable symlink missing: $WANTS"
[ -x "$SETUP" ]   || fail "setup script missing/not executable: $SETUP"
[ -f "$ONESHOT" ] || fail "setup oneshot missing: $ONESHOT"
[ -f "$CARD" ]    || fail "portal card missing: $CARD"

# Build-time / not-yet-provisioned machines have no live server — that's OK.
if command -v curl >/dev/null 2>&1 \
    && curl -fsS -m 4 http://127.0.0.1:8788/health >/dev/null 2>&1; then
    echo "dev-ai-hermes-webui: healthy on 127.0.0.1:8788"
    exit 0
fi

echo "dev-ai-hermes-webui: files installed; server not running yet " \
     "(needs ~/.hermes/hermes-agent + first-boot setup)" >&2
exit 2
