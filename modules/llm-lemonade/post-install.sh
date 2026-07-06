#!/bin/sh
# post-install.sh — llm-lemonade
# Build-time only: enable the unit (a symlink write, not a running
# process) and stage the port marker. NO systemctl --now (build has no
# running init) and no device check here — the build container never has
# /dev/accel/accel0 regardless of the real target machine, so gating
# `systemctl enable` on it here would always skip it. The unit's own
# ConditionPathExists=/dev/accel/accel0 is what actually gates whether the
# service starts, evaluated for real at boot on the deployed machine.
set -eu

mkdir -p /etc/aipc/env.d/llm-lemonade
printf '8001\n' > /etc/aipc/env.d/llm-lemonade/port

chmod 0755 /usr/lib/aipc/llm-lemonade/configure-lemonade.sh

systemctl enable lemonade.service
