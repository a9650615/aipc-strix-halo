#!/bin/sh
# post-install.sh — db-postgres
# Build-time only. Service start + schema init happen at runtime via
# aipc-pg-init.service (see files/etc/systemd/system/).
set -eu

# Ensure /var/lib/aipc-pg exists at build time so the runtime sentinel has a home.
install -d -m 0700 /var/lib/aipc-pg

# Enable the postgres quadlet + the init oneshot (NOT --now — runtime starts them).
systemctl enable postgres.service
systemctl enable aipc-pg-init.service
