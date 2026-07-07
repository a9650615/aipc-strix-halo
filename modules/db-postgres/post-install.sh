#!/bin/sh
# post-install.sh — db-postgres
# Build-time only. Service start + schema init happen at runtime via
# aipc-pg-init.service (see files/etc/systemd/system/).
#
# The postgres quadlet at /etc/containers/systemd/postgres.container is
# auto-loaded by systemd on next boot (quadlet integration), so no
# `systemctl enable postgres.service` here — it would fail inside the
# build container where systemd isn't PID 1.
set -eu

# Ensure /var/lib/aipc-pg exists at build time so the runtime sentinel has a home.
install -d -m 0700 /var/lib/aipc-pg

# Enable the init oneshot (NOT --now — runtime starts it).
systemctl enable aipc-pg-init.service
