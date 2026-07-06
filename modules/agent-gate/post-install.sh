#!/bin/sh
# post-install.sh — agent-gate
# BUILD-TIME ONLY. No running services during image build.
set -eu

mkdir -p /var/lib/aipc-agent

systemctl enable aipc-agent-gate.service
