#!/bin/sh
# post-install.sh — agent-screen-control
# BUILD-TIME ONLY. No running services during image build.
set -eu
# Config files delivered via files/ tree.

# ydotool.service ships (disabled by Fedora preset) in the ydotool package
# from packages.txt. input.py needs ydotoold running to inject events, so
# enable the base unit at build time (symlink write only, no --now — the
# build container has no running init). The socket-path override that
# points it at a uid-1000-owned socket, plus the boot-race fix, live in
# files/etc/systemd/system/ydotool.service.d/override.conf (see README).
systemctl enable ydotool.service
