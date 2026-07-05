#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

/usr/lib/aipc-rag/venv/bin/python3 -c \
  "import aipc_rag.desktop, aipc_rag.code, aipc_rag.browser, aipc_rag.screen_audio" || {
    echo "rag-ingest: aipc_rag package failed to import" >&2
    exit 1
}

for svc in aipc-rag-desktop aipc-rag-code; do
  systemctl is-active --quiet "$svc.service" || {
    echo "rag-ingest: $svc not active" >&2
    exit 1
  }
done

for svc in aipc-rag-browser-firefox aipc-rag-browser-chrome aipc-rag-screen-audio; do
  if systemctl is-active --quiet "$svc.service"; then
    : # user opted in
  else
    echo "rag-ingest: $svc disabled by default (consent-gated)" >&2
  fi
done

exit 0
