#!/bin/sh
# post-install.sh — voice-pipecat
# BUILD-TIME ONLY. No services started, no listeners probed.
set -eu

chmod +x /usr/bin/aipc-voice-once
chmod +x /usr/bin/aipc-voice-stream
chmod +x /usr/bin/aipc-voice-template
chmod +x /usr/bin/aipc-voice-say
mkdir -p /var/lib/aipc-voice/persona/templates
