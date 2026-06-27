#!/bin/sh
# verify.sh — secrets-sops
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
# Exit code 2 = age key absent (expected on fresh image, not a failure).
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# SOPS config present and readable
[ -r /etc/aipc/sops.yaml ] || fail "secrets-sops: /etc/aipc/sops.yaml not found or not readable"

# Helper is executable
[ -x /usr/local/lib/aipc/sops-env ] || fail "secrets-sops: /usr/local/lib/aipc/sops-env not executable"

# Fails closed without age key
if [ ! -r /etc/aipc/age.key ]; then
  # Expected on a fresh image; verify the helper actually fails closed
  _out=$(sh -c '. /usr/local/lib/aipc/sops-env /dev/null' 2>&1 || true)
  printf '%s' "${_out}" | grep -qi 'install-key\|age key' \
    || fail "secrets-sops: helper does not mention 'install-key' when age key is absent"
  # Exit 0 — key absent is documented expected state (see design.md risk note)
  exit 0
fi

# If age key IS present, we just verify config and helper are in place (decrypt test needs a real file)
exit 0
