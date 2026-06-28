#!/bin/sh
# verify.sh — ai-rocm
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# rocm-smi present and lists a gfx1151 device
command -v rocm-smi >/dev/null 2>&1 || fail "ai-rocm: rocm-smi not found on PATH"
rocm_info=$(rocm-smi --showproductname 2>/dev/null) || fail "ai-rocm: rocm-smi --showproductname failed (no GPU visible?)"
echo "${rocm_info}" | grep -qi "gfx1151" || fail "ai-rocm: no gfx1151 device reported by rocm-smi"

# GTT >= 115360 MiB (per OpenSpec task 2.1 threshold)
gtt_mb=$(dmesg 2>/dev/null | grep -i 'amdgpu.*gtt' | grep -oE 'GTT size: [0-9]+' | grep -oE '[0-9]+' | tail -1)
[ -n "${gtt_mb}" ] || fail "ai-rocm: GTT line not found in dmesg (amdgpu not loaded?)"
[ "${gtt_mb}" -ge 115360 ] || fail "ai-rocm: GTT ${gtt_mb} MiB < 115360 MiB required"
