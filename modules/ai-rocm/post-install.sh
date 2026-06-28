#!/bin/sh
# post-install.sh — ai-rocm
# Idempotent: safe to re-run on image rebuilds.
set -eu

repo_file=/etc/yum.repos.d/rocm.repo
repo_url=https://repo.radeon.com/rocm/yum/7.0/rocm-7.0.repo

if [ ! -f "${repo_file}" ]; then
  dnf config-manager --add-repo "${repo_url}"
fi

pkgs="rocm-smi amd-smi rocm-hip-runtime"
for pkg in ${pkgs}; do
  rpm -q "${pkg}" >/dev/null 2>&1 || dnf install -y "${pkg}"
done
