#!/bin/sh
set -eu
# Static / light runtime
python3 - <<'PY' || {
  echo "voice-audio-front: self_test failed" >&2
  exit 1
}
import sys
sys.path.insert(0, "/usr/lib/aipc-voice")
sys.path.insert(0, "/var/lib/aipc-voice/lib")
from aipc_audio_front.server import self_test
self_test()
PY

if systemctl is-active --quiet aipc-voice-audio-front.service 2>/dev/null; then
  curl -fsS -m 2 http://127.0.0.1:9010/healthz >/dev/null || {
    echo "voice-audio-front: healthz failed while unit active" >&2
    exit 1
  }
fi
exit 0
