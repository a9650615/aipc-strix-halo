#!/bin/sh
# post-install.sh — voice-tts-cosyvoice
# BUILD-TIME ONLY.
set -eu

mkdir -p /etc/aipc/cosyvoice/voices

systemctl enable aipc-cosyvoice.service
