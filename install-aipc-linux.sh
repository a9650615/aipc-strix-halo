#!/usr/bin/env bash
set -eu

cd "$(dirname "${BASH_SOURCE[0]}")"
exec bash tools/bootstrap.sh "$@"
