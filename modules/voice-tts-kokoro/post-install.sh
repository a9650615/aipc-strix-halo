#!/bin/sh
# post-install.sh — voice-tts-kokoro
# BUILD-TIME ONLY. Do not pull the image or start the container here
# (CLAUDE.md §8). Quadlet enables the unit; first boot pulls the image.
set -eu

# Disable the old stdlib espeak unit if an earlier image shipped it.
systemctl disable aipc-voice-tts-local.service 2>/dev/null || true

# Quadlet unit is generated from quadlet/aipc-kokoro.container by the
# renderer; nothing else to enable at build time beyond package presence.
true
