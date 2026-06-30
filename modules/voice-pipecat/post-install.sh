#!/bin/sh
# post-install.sh — voice-pipecat
# BUILD-TIME ONLY. No services started, no listeners probed.
set -eu

mkdir -p /etc/aipc/pipecat
mkdir -p /etc/aipc/env.d/voice-pipecat

systemctl enable aipc-voice-pipecat.service
