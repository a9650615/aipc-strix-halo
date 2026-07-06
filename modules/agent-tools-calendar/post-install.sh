#!/bin/sh
# post-install.sh — agent-tools-calendar
# BUILD-TIME ONLY.
set -eu
# Config files and library package delivered via files/ tree.
# No secrets baked — user configures at firstboot (Google OAuth token,
# Proton/Fastmail password files below are written by hand, never here).
mkdir -p /var/lib/aipc-agent/oauth /var/lib/aipc-agent/secrets
chmod 700 /var/lib/aipc-agent/oauth /var/lib/aipc-agent/secrets
