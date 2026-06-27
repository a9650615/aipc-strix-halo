#!/bin/sh
# post-install.sh — system-base
# Idempotent: safe to re-run on image rebuilds.
set -eu

# Timezone: Asia/Taipei
tz_target="/usr/share/zoneinfo/Asia/Taipei"
if [ ! -e "${tz_target}" ]; then
  printf 'post-install system-base: %s not found — tzdata missing?\n' "${tz_target}" >&2
  exit 1
fi
ln -sf "${tz_target}" /etc/localtime

# Branding: substitute PLACEHOLDERs from env vars injected by renderer
branding="/etc/aipc/branding.env"
if [ -z "${AIPC_IMAGE_REF:-}" ] || [ -z "${AIPC_BUILD_DATE:-}" ]; then
  printf 'post-install system-base: AIPC_IMAGE_REF and AIPC_BUILD_DATE must be set\n' >&2
  exit 1
fi
mkdir -p /etc/aipc
printf 'IMAGE_REF=%s\nBUILD_DATE=%s\n' "${AIPC_IMAGE_REF}" "${AIPC_BUILD_DATE}" > "${branding}"
