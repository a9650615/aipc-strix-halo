#!/bin/sh
# post-install.sh — ops-firstboot
# Build-time: wizard config, unit, and aipc-init shim are already staged at
# their final destinations by the renderer's `COPY modules/ops-firstboot/files/ /`
# step. NO systemctl --now (build has no running init) — enable only.
set -eu

chmod 0755 /usr/lib/aipc/aipc-init
systemctl enable aipc-firstboot.service
