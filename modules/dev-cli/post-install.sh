#!/bin/sh
set -eu

primary_user="${AIPC_PRIMARY_USER:-${SUDO_USER:-$(logname 2>/dev/null || echo root)}}"

if [ -x /usr/bin/fish ]; then
  current_shell=$(getent passwd "${primary_user}" | cut -d: -f7)
  if [ "${current_shell}" != "/usr/bin/fish" ]; then
    chsh -s /usr/bin/fish "${primary_user}" || true
  fi
fi
