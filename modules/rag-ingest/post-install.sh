#!/bin/sh
set -eu

if command -v pip >/dev/null 2>&1; then
  pip install --quiet aipc-rag-ingest || true
fi

systemctl enable --now aipc-rag-desktop.service || true
systemctl enable --now aipc-rag-code.service || true
