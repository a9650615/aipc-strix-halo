#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

systemctl is-active --quiet qdrant.service || {
  echo "qdrant: service not active" >&2
  exit 1
}

curl -sf http://127.0.0.1:6333/ >/dev/null || {
  echo "qdrant: / endpoint unreachable" >&2
  exit 1
}

exit 0
