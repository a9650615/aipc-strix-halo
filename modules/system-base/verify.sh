#!/bin/sh
# verify.sh — system-base
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# Required tools on PATH
for cmd in jq yq sops age btrfs snapper rg fzf delta; do
  command -v "${cmd}" >/dev/null 2>&1 || fail "system-base: ${cmd} not found on PATH"
done

# Timezone
tz_link=$(readlink /etc/localtime 2>/dev/null) || fail "system-base: /etc/localtime is not a symlink"
case "${tz_link}" in
  */Asia/Taipei) ;;
  *) fail "system-base: /etc/localtime points to '${tz_link}', expected .../Asia/Taipei" ;;
esac

# Branding stamped (no PLACEHOLDER values)
branding="/etc/aipc/branding.env"
[ -r "${branding}" ] || fail "system-base: ${branding} not found"
grep -q 'PLACEHOLDER' "${branding}" && fail "system-base: ${branding} still contains PLACEHOLDER — branding not stamped"
grep -q '^IMAGE_REF=' "${branding}" || fail "system-base: IMAGE_REF missing from ${branding}"
grep -q '^BUILD_DATE=' "${branding}" || fail "system-base: BUILD_DATE missing from ${branding}"
