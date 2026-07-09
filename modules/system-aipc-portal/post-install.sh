#!/bin/sh
# post-install.sh — system-aipc-portal
# BUILD-TIME ONLY. No systemctl --now, no health loops.
set -eu

chmod 0755 /usr/lib/aipc-portal/aipc-portal 2>/dev/null || true
systemctl enable aipc-portal.service >/dev/null 2>&1 || true
