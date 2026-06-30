#!/bin/sh
# pg-init.sh — runtime postgres schema bootstrap, idempotent
set -eu

# Wait up to 60s for postgres to accept connections.
for _ in $(seq 1 60); do
    if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    echo "pg-init: postgres not ready after 60s" >&2
    exit 1
fi

# Create db if missing.
psql -h 127.0.0.1 -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='aipc'" \
    | grep -q 1 || psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE aipc"

# Apply pgvector extension + any future schema. The SQL file is idempotent
# (uses CREATE EXTENSION IF NOT EXISTS).
psql -h 127.0.0.1 -U postgres -d aipc -f /usr/lib/aipc/init-pgvector.sql

# Mark complete to prevent re-runs.
touch /var/lib/aipc-pg/.initialized
