#!/bin/sh
set -eu

if [ ! -f /etc/aipc/vllm/enabled ]; then
  systemctl disable --now vllm.service 2>/dev/null || true
  exit 0
fi

systemctl enable --now vllm.service
