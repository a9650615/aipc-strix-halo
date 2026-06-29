#!/bin/sh
set -eu

systemctl enable --now postgres.service

for i in $(seq 1 30); do
  if nc -z 127.0.0.1 5432 2>/dev/null; then
    break
  fi
  sleep 1
done

if ! nc -z 127.0.0.1 5432 2>/dev/null; then
  echo "postgres: port 5432 not reachable after 30s" >&2
  exit 1
fi

if command -v psql >/dev/null 2>&1; then
  psql -h 127.0.0.1 -U postgres -d aipc -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null 2>&1 || true
fi
