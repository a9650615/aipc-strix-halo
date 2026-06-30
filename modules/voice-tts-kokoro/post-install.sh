#!/bin/sh
# post-install.sh — voice-tts-kokoro
# BUILD-TIME ONLY.
set -eu

systemctl enable aipc-kokoro.service
