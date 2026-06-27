#!/bin/sh
# post-install.sh — secrets-sops
# Idempotent: safe to re-run on image rebuilds.
set -eu

chmod 0755 /usr/local/lib/aipc/sops-env
chmod 0644 /etc/aipc/sops.yaml
