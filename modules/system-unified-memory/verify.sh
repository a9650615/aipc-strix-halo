#!/bin/sh
# verify.sh — system-unified-memory
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# GTT >= 120 GiB (122880 MiB)
gtt_mb=$(dmesg 2>/dev/null | grep -i 'amdgpu.*gtt' | grep -oE 'GTT size: [0-9]+' | grep -oE '[0-9]+' | tail -1)
[ -n "${gtt_mb}" ] || fail "system-unified-memory: GTT line not found in dmesg (amdgpu not loaded?)"
[ "${gtt_mb}" -ge 122880 ] || fail "system-unified-memory: GTT ${gtt_mb} MiB < 122880 MiB required"

# rocm-smi sees a device
command -v rocm-smi >/dev/null 2>&1 || fail "system-unified-memory: rocm-smi not found on PATH"
rocm-smi --showid >/dev/null 2>&1 || fail "system-unified-memory: rocm-smi --showid failed (no GPU visible?)"

# HSA env drop-in exists and sets HSA_OVERRIDE_GFX_VERSION
hsa_file="/etc/aipc/env.d/system-unified-memory/hsa.sh"
[ -r "${hsa_file}" ] || fail "system-unified-memory: ${hsa_file} not found"
# shellcheck source=/dev/null
. "${hsa_file}"
[ "${HSA_OVERRIDE_GFX_VERSION:-}" = "11.5.1" ] || fail "system-unified-memory: HSA_OVERRIDE_GFX_VERSION not 11.5.1 after sourcing ${hsa_file}"

# NPU visible via lspci
lspci 2>/dev/null | grep -qiE 'signal processing|xdna' || fail "system-unified-memory: XDNA NPU not visible via lspci"

# Panel Replay workaround applied (0x400 = DC_DISABLE_REPLAY)
dcdebugmask_file="/sys/module/amdgpu/parameters/dcdebugmask"
[ -r "${dcdebugmask_file}" ] || fail "system-unified-memory: ${dcdebugmask_file} not found (amdgpu not loaded?)"
dcdebugmask=$(cat "${dcdebugmask_file}")
[ $((dcdebugmask & 0x400)) -ne 0 ] || fail "system-unified-memory: dcdebugmask=${dcdebugmask} does not include 0x400 (DC_DISABLE_REPLAY)"
