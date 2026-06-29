#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

systemctl is-active --quiet postgres.service || {
  echo "postgres: service not active" >&2
  exit 1
}

nc -z 127.0.0.1 5432 || {
  echo "postgres: port 5432 not reachable" >&2
  exit 1
}

if command -v psql >/dev/null 2>&1; then
  psql -h 127.0.0.1 -U postgres -d aipc -tc \
    "SELECT 1 FROM pg_extension WHERE extname='vector';" | grep -q 1 || {
    echo "postgres: pgvector extension not loaded" >&2
    exit 1
  }
fi

exit 0
