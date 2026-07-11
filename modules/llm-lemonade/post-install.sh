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
chmod 0755 /usr/lib/aipc/llm-lemonade/ensure-resident-small.sh
# Live path used by aipc-resident-small.service (SELinux-friendly under /etc)
mkdir -p /etc/aipc/llm-lemonade
cp -a /usr/lib/aipc/llm-lemonade/ensure-resident-small.sh \
  /etc/aipc/llm-lemonade/ensure-resident-small.sh
chmod 0755 /etc/aipc/llm-lemonade/ensure-resident-small.sh

systemctl enable lemonade.service
# Pin + warm resident-small (FLM) after lemonade so LRU cannot evict the
# always-on NPU chat model (see ensure-resident-small.sh header).
systemctl enable aipc-resident-small.service
