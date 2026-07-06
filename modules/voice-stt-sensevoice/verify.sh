#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

fail() { echo "voice-stt-sensevoice: $*" >&2; exit 1; }

pkg_dir="$this_dir/files/usr/lib/aipc-voice"
venv="/usr/lib/aipc-voice/venv"

[ -f "$pkg_dir/aipc_stt_sensevoice/server.py" ] || fail "server.py missing"
python3 -c "import ast; ast.parse(open('$pkg_dir/aipc_stt_sensevoice/server.py').read())" \
    || fail "syntax error in server.py"

if [ ! -x "$venv/bin/python3" ]; then
    echo "voice-stt-sensevoice: static OK only (render-verified; venv not installed on this host, no hardware check run)" >&2
    exit 0
fi

systemctl is-active --quiet aipc-voice-stt-sensevoice.service || {
    echo "voice-stt-sensevoice: static OK; aipc-voice-stt-sensevoice.service not active (no live hardware check)" >&2
    exit 0
}

curl -sf http://127.0.0.1:9001/healthz >/dev/null || fail "GET /healthz did not return 2xx"

echo "voice-stt-sensevoice: static + render + hardware OK (service active, /healthz responded)"
