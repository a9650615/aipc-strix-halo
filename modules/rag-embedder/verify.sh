#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

systemctl is-active --quiet rag-embedder.service || {
  echo "rag-embedder: service not active" >&2
  exit 1
}

curl -sf http://127.0.0.1:8201/healthz >/dev/null || {
  echo "rag-embedder: /healthz unreachable" >&2
  exit 1
}

exit 0
