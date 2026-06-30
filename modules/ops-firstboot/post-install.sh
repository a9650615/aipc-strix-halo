#!/bin/sh
# post-install.sh — ops-firstboot
# Build-time: install systemd unit, wizard config, and aipc-init shim.
# NO systemctl --now (build has no running init).
set -eu

install -Dm0644 \
    "${AIPC_MODULE_SRC}/files/etc/aipc/firstboot/wizard.yaml" \
    /etc/aipc/firstboot/wizard.yaml

install -Dm0644 \
    "${AIPC_MODULE_SRC}/files/etc/systemd/system/aipc-firstboot.service" \
    /etc/systemd/system/aipc-firstboot.service

install -Dm0755 \
    "${AIPC_MODULE_SRC}/files/usr/lib/aipc/aipc-init" \
    /usr/lib/aipc/aipc-init

systemctl enable aipc-firstboot.service
