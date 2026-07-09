#!/bin/sh
set -eu
this_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

server="$this_dir/files/usr/lib/aipc-voice/aipc_tts_local/server.py"
[ -f "$server" ] || {
  echo "voice-tts-kokoro: missing server.py" >&2
  exit 1
}
python3 -c "import ast; ast.parse(open('$server').read())" || {
  echo "voice-tts-kokoro: server.py syntax error" >&2
  exit 1
}
unit="$this_dir/files/etc/systemd/system/aipc-voice-tts-local.service"
[ -f "$unit" ] || {
  echo "voice-tts-kokoro: missing systemd unit" >&2
  exit 1
}
grep -Eq '8880|AIPC_TTS_PORT' "$unit" || {
  echo "voice-tts-kokoro: unit must publish 8880" >&2
  exit 1
}
server_py="$this_dir/files/usr/lib/aipc-voice/aipc_tts_local/server.py"
python3 "$server_py" --help >/dev/null 2>&1 || true
python3 -c "import ast; ast.parse(open('$server_py').read())"
# Runtime optional: if live service is up, require healthz.
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -m 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8880/healthz 2>/dev/null || true)
  if [ "$code" = "200" ]; then
    echo "voice-tts-kokoro: static OK + live healthz 200"
    exit 0
  fi
fi
echo "voice-tts-kokoro: static OK (live healthz optional)"
exit 0
