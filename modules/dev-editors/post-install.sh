#!/bin/sh
set -eu

# Install (runtime, user-initiated):
#   - Zed:           flatpak install flathub dev.zed.Zed
#   - VSCode:        flatpak install flathub com.visualstudio.code
#   - JetBrains CL:  ujust ide install jetbrains-client
#
# Build-time only installs dev fonts (jetbrains-mono, fira-code) via rpm.
# Editors themselves are NOT installed at build time: VSCode is not a
# Fedora rpm (bazzite ships IDEs via Brew/Flatpak/ujust), and flatpak
# install requires network (violates offline-build).
#
# Skel configs (for when user installs editors at runtime):
#   - /etc/skel/.config/zed/settings.json routes Zed AI to LiteLLM
#   - /etc/skel/.config/Code/settings.json routes VSCode extensions to LiteLLM
