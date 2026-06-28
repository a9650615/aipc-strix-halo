#!/bin/sh
# post-install.sh — secrets-sops
# Idempotent: safe to re-run on image rebuilds.
# ponytail: sops is not in bazzite-dx repo, fetch the upstream binary;
# upgrade path = bump SOPS_VERSION below.
set -eu

SOPS_VERSION=3.9.2

if [ ! -x /usr/local/bin/sops ] || ! /usr/local/bin/sops --version 2>/dev/null | grep -q "$SOPS_VERSION"; then
    curl -fsSL -o /usr/local/bin/sops \
        "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64"
    chmod 0755 /usr/local/bin/sops
fi

chmod 0755 /usr/local/lib/aipc/sops-env
chmod 0644 /etc/aipc/sops.yaml
