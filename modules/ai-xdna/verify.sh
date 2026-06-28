#!/bin/sh
# verify.sh — ai-xdna
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# Kernel module loaded
lsmod | grep -q '^amd_xdna' || fail "ai-xdna: amd_xdna kernel module not loaded"

# Device node exists
[ -e /dev/accel/accel0 ] || fail "ai-xdna: /dev/accel/accel0 not found"

# xdna-smi enumerates at least one NPU
command -v xdna-smi >/dev/null 2>&1 || fail "ai-xdna: xdna-smi not found on PATH"
xdna-smi examine >/dev/null 2>&1 || fail "ai-xdna: xdna-smi examine failed (NPU not responding?)"
