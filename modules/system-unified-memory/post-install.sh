#!/bin/sh
# post-install.sh — system-unified-memory
# Build-time: enable the GPP0/GPP1 wake-source fix unit. NO systemctl --now
# (build has no running init) — the unit's [Install] WantedBy=default.target
# runs it at real boot, before the user has a chance to suspend.
set -eu

chmod 0755 /usr/lib/aipc/gpp-wake-fix
systemctl enable gpp-wake-fix.service

chmod 0755 /usr/lib/aipc/platform-profile-auto /usr/lib/systemd/system-sleep/platform-profile-resume
systemctl enable platform-profile-auto.service

chmod 0755 /usr/lib/aipc/platform-profile-idle-check
systemctl enable platform-profile-idle-check.timer

# Hardware-verified 2026-07-04: the default targeted policy denies even a
# root systemd service (runs as init_t) writing to /proc/acpi/wakeup
# (proc_t) -- confirmed via ausearch -m avc showing `denied { write }`.
# This custom module grants exactly that one write, nothing broader
# (source .te lives at modules/system-unified-memory/selinux/ for review;
# regenerate the .pp with `checkmodule -M -m -o x.mod x.te && semodule_package
# -o x.pp -m x.mod` if the .te ever changes). semodule only touches the
# policy store on disk -- no live kernel/enforcement needed, safe at build time.
semodule -i /usr/share/selinux/packages/gpp_wake_fix.pp
