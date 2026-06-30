#!/bin/sh
# post-install.sh — agent-code-shell
# BUILD-TIME ONLY. Installs distrobox-assemble template, does NOT spawn the box.
set -eu

# Template is in files/ — already copied by renderer.
# Idempotency: nothing to do beyond file presence.
