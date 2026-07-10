#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"

fail() { echo "voice-tts-cosyvoice: $*" >&2; exit 1; }

server="$this_dir/files/usr/lib/aipc-voice/aipc_tts_cosyvoice/server.py"
unit="$this_dir/files/etc/systemd/system/aipc-voice-tts-cosyvoice.service"

[ -f "$server" ] || fail "server.py missing"
[ -f "$unit" ] || fail "systemd unit missing"

# No fictitious container image under quadlet/ (the old scaffold lived there).
if [ -d "$this_dir/quadlet" ]; then
  fail "quadlet/ must be removed (native systemd replaces fictitious container)"
fi

python3 -c "import ast; ast.parse(open('$server').read())" \
  || fail "syntax error in server.py"

grep -q '9880' "$unit" || fail "unit must bind port 9880"
grep -q 'aipc-voice-tts-cosyvoice' "$unit" || fail "unit Description/name mismatch"
grep -q 'AIPC_COSYVOICE_DEVICE=cpu' "$unit" || fail "unit must default device=cpu"
grep -q 'Fun-CosyVoice3-0.5B-2512' "$unit" || fail "unit must point at CosyVoice3 model"
grep -q 'Restart=on-failure' "$unit" || fail "unit must Restart=on-failure"

if [ -f "$this_dir/.disabled" ]; then
  echo "voice-tts-cosyvoice: static OK; disabled (optional, awaiting hardware-verify)" >&2
  exit 2
fi

# Live optional
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -m 3 -o /tmp/cosyvoice-hz -w '%{http_code}' \
    http://127.0.0.1:9880/healthz 2>/dev/null || true)
  if [ "$code" = "200" ]; then
    body=$(head -c 300 /tmp/cosyvoice-hz 2>/dev/null || true)
    echo "voice-tts-cosyvoice: static OK + live healthz ($body)"
    exit 0
  fi
fi

echo "voice-tts-cosyvoice: static OK (live healthz optional)"
exit 0
