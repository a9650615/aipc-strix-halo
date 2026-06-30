#!/bin/sh
# post-install.sh — ops-backup
# Build-time: install snapper config and subvolume list.
set -eu

install -Dm0644 \
    "${AIPC_MODULE_SRC}/files/etc/snapper/configs/aipc-root" \
    /etc/snapper/configs/aipc-root

install -Dm0644 \
    "${AIPC_MODULE_SRC}/files/etc/aipc/backup/subvols" \
    /etc/aipc/backup/subvols
