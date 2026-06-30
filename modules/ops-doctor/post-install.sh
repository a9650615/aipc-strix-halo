#!/bin/sh
# post-install.sh — ops-doctor
# Build-time: install service catalog config.
set -eu

install -Dm0644 \
    "${AIPC_MODULE_SRC}/files/etc/aipc/doctor/services.yaml" \
    /etc/aipc/doctor/services.yaml
