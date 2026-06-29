#!/bin/sh
set -eu

if ! flatpak list --system 2>/dev/null | grep -q dev.zed.Zed; then
  flatpak install -y --system flathub dev.zed.Zed 2>/dev/null || true
fi
