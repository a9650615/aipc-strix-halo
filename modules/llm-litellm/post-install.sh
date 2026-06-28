#!/bin/sh
# post-install.sh — llm-litellm
# Idempotent: safe to re-run during image rebuilds or recovery.
set -eu

CONFIG_DIR=/etc/aipc/litellm
CONFIG_SRC=/usr/share/aipc/llm-litellm/config.yaml
CONFIG_DST=${CONFIG_DIR}/config.yaml
ENV_DIR=/etc/aipc/env.d/llm-litellm

mkdir -p "${CONFIG_DIR}" "${ENV_DIR}"

if [ ! -f "${CONFIG_DST}" ] && [ -f "${CONFIG_SRC}" ]; then
  cp "${CONFIG_SRC}" "${CONFIG_DST}"
fi

cp /usr/share/aipc/llm-litellm/endpoint "${ENV_DIR}/endpoint" 2>/dev/null || true

mkdir -p ~/.config/containers/systemd
install -m 0644 /usr/share/aipc/llm-litellm/litellm.service \
  ~/.config/containers/systemd/litellm.service

systemctl --user daemon-reload
systemctl --user enable --now litellm.service
