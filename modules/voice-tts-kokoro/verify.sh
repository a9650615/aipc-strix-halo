#!/bin/sh
set -eu
this_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

quadlet="$this_dir/quadlet/aipc-kokoro.container"
[ -f "$quadlet" ] || {
  echo "voice-tts-kokoro: missing quadlet" >&2
  exit 1
}
grep -q 'ghcr.io/remsky/kokoro-fastapi' "$quadlet" || {
  echo "voice-tts-kokoro: quadlet must pin Kokoro-FastAPI image" >&2
  exit 1
}
grep -q '8880' "$quadlet" || {
  echo "voice-tts-kokoro: must publish 8880" >&2
  exit 1
}
# Live optional
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -m 3 -o /tmp/kokoro-hz -w '%{http_code}' http://127.0.0.1:8880/health 2>/dev/null || true)
  code2=$(curl -s -m 3 -o /tmp/kokoro-hz2 -w '%{http_code}' http://127.0.0.1:8880/healthz 2>/dev/null || true)
  if [ "$code" = "200" ] || [ "$code2" = "200" ]; then
    body=$(cat /tmp/kokoro-hz /tmp/kokoro-hz2 2>/dev/null | head -c 200)
    echo "voice-tts-kokoro: static OK + live health ($body)"
    exit 0
  fi
fi
echo "voice-tts-kokoro: static OK (live Kokoro optional)"
exit 0
