#!/bin/sh
# post-install.sh — voice-wake
# BUILD-TIME ONLY.
set -eu

mkdir -p /var/lib/aipc-voice/wake/samples
chmod +x /usr/bin/aipc-voice-train-wake /usr/libexec/aipc-voice-mute-screenlock \
  /usr/lib/aipc-voice/aipc_voice_wake.py 2>/dev/null || true

systemctl enable aipc-voice-wake.service
systemctl enable aipc-voice-mute.service 2>/dev/null || true
