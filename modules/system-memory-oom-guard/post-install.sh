#!/bin/sh
# Build-time only (§8): enable the unit (a symlink write, not a running
# process) and stage the state dir. NO systemctl --now — the build
# container has no running init, and the daemon must read the host /proc
# and /sys/fs/cgroup that the build container doesn't have anyway.
set -e
install -d -m 0755 /var/lib/aipc-oom-guard
systemctl enable oom-guard.service 2>/dev/null || true
