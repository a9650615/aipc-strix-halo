#!/bin/sh
# post-install.sh — agent-tools-files
# BUILD-TIME ONLY. No running services during image build.
set -eu

# Config file and library package delivered via files/ tree.
# Default workspace root (files-allowlist.conf roots[0]) — created empty,
# populated at runtime by whichever sub-agent writes into it.
mkdir -p /var/lib/aipc-agent/workspace
