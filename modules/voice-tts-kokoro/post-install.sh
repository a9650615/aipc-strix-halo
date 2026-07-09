#!/bin/sh
# post-install.sh — voice-tts-kokoro (local TTS service)
# BUILD-TIME ONLY. No running services (CLAUDE.md §8).
set -eu

# Stdlib server needs no venv; ensure scripts are executable.
chmod +x /usr/lib/aipc-voice/aipc_tts_local/server.py 2>/dev/null || true

systemctl enable aipc-voice-tts-local.service
