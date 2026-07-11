#!/bin/sh
set -eu
# Ship package into shared aipc-voice lib tree (same as sensevoice/wake).
if [ -d /usr/lib/aipc-voice/aipc_audio_front ]; then
  :
fi
systemctl enable aipc-voice-audio-front.service || true
