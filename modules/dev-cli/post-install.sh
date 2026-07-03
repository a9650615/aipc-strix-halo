#!/bin/sh
set -eu

primary_user="${AIPC_PRIMARY_USER:-${SUDO_USER:-$(logname 2>/dev/null || echo root)}}"

if [ -x /usr/bin/fish ]; then
  current_shell=$(getent passwd "${primary_user}" | cut -d: -f7)
  if [ "${current_shell}" != "/usr/bin/fish" ]; then
    chsh -s /usr/bin/fish "${primary_user}" || true
  fi
fi

# btop's show_cpu_watts reads /sys/class/powercap/intel-rapl:0/energy_uj, which is
# root-only (0400) by default; grant cap_dac_read_search so it works for the regular
# user without sudo/setuid. Build-time safe: setcap only touches the file's xattr.
if [ -x /usr/bin/btop ]; then
  setcap cap_dac_read_search+ep /usr/bin/btop
fi
