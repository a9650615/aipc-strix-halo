#!/bin/sh
# post-install.sh — llm-lemonade
set -eu

mkdir -p /etc/aipc/env.d/llm-lemonade
printf '8001\n' > /etc/aipc/env.d/llm-lemonade/port

install -D -m 0644 "$(dirname "$0")/quadlet/lemonade.service" \
    /etc/systemd/system/lemonade.service
install -D -m 0644 "$(dirname "$0")/files/etc/aipc/lemonade/models.yaml" \
    /etc/aipc/lemonade/models.yaml

systemctl daemon-reload

if [ ! -e /dev/accel/accel0 ]; then
    printf 'post-install llm-lemonade: /dev/accel/accel0 not found — leaving service disabled\n' >&2
    exit 0
fi

systemctl enable --now lemonade.service
