#!/bin/sh
# post-install.sh — voice-wake
# BUILD-TIME ONLY.
set -eu

mkdir -p /var/lib/aipc-voice/wake/samples
chmod +x /usr/bin/aipc-voice-train-wake /usr/libexec/aipc-voice-mute-screenlock \
  /usr/lib/aipc-voice/aipc_voice_wake.py \
  /usr/lib/systemd/system-sleep/aipc-ai-stack 2>/dev/null || true

systemctl enable aipc-voice-wake.service
systemctl enable aipc-voice-mute.service 2>/dev/null || true

# Sleep/resume recovery for always-on voice (ostree: script lives under /var)
mkdir -p /var/lib/aipc-voice/bin
if [ -f /var/lib/aipc-voice/bin/aipc-ai-stack-sleep ]; then
  chmod +x /var/lib/aipc-voice/bin/aipc-ai-stack-sleep
fi
systemctl enable aipc-ai-sleep-pre.service aipc-ai-sleep-post.service 2>/dev/null || true
