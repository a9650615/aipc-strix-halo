#!/bin/sh
# post-install.sh — agent-code-shell
# BUILD-TIME ONLY. Installs distrobox-assemble template + wrapper, does NOT
# spawn the box (no distrobox/podman daemon exists at build time) and does
# NOT run Open Interpreter's install (that's the template's own init_hooks,
# which distrobox runs at first-assemble on the running machine — task 3.3).
set -eu

# Template is in files/ — already copied by renderer.
chmod +x /usr/lib/aipc-agent/aipc-code-shell
ln -sf /usr/lib/aipc-agent/aipc-code-shell /usr/bin/aipc-code-shell
