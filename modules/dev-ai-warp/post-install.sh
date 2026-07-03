#!/bin/sh
# post-install.sh — dev-ai-warp
# Build-time: install warp-terminal from the repo file already staged at
# /etc/yum.repos.d/warpdotdev.repo by the renderer's `COPY .../files/ /`
# step. This is a real package install from a declared repo, unlike a
# runtime curl|sh installer — safe to run at build time (no running
# service assumed, matches the ai-rocm pattern).
#
# /opt is a symlink to var/opt on this ostree-based image (same pattern as
# /home -> var/home), and var/opt doesn't exist yet at this point in the
# build. warp-terminal's RPM installs into /opt/warpdotdev/, so its cpio
# unpack fails with a confusing "mkdir failed - File exists" / "No such
# file or directory" pair without this. Hardware/build-verified 2026-07-03.
set -eu

mkdir -p /var/opt
rpm-ostree install -y warp-terminal
