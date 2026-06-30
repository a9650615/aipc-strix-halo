#!/bin/sh
# post-install.sh — voice-wake
# BUILD-TIME ONLY. Installs training scaffolds; does NOT run training.
set -eu

mkdir -p /etc/aipc/wake
mkdir -p /var/lib/aipc/wake

systemctl enable aipc-voice-wake.service
