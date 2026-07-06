#!/bin/sh
# post-install.sh — voice-stt-sensevoice
# BUILD-TIME ONLY. No running services, no GPU/NPU, network limited to
# package/pip repos (CLAUDE.md §8). Model weights are NOT fetched here —
# funasr.AutoModel downloads iic/SenseVoiceSmall on first run into
# MODELSCOPE_CACHE (see the systemd unit), the first time the service starts
# with network available.
set -eu

python3 -m venv /usr/lib/aipc-voice/venv
/usr/lib/aipc-voice/venv/bin/pip install --no-cache-dir -r /usr/lib/aipc-voice/requirements.txt

mkdir -p /var/lib/aipc-voice/models

systemctl enable aipc-voice-stt-sensevoice.service
