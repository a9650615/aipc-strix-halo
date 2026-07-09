#!/bin/sh
# post-install.sh — voice-tts-cosyvoice
# BUILD-TIME ONLY (CLAUDE.md §8). No model download, no systemctl --now,
# no curl healthchecks. CosyVoice git checkout + weights + venv are a
# runtime concern (manual or first-boot oneshot — see README).
set -eu

mkdir -p /var/lib/aipc-voice/persona
mkdir -p /var/lib/aipc-voice/models/cosyvoice2
mkdir -p /var/lib/aipc-voice/cosyvoice

systemctl enable aipc-voice-tts-cosyvoice.service
