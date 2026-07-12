#!/bin/sh
# post-install.sh — dev-ai-hermes-webui
# BUILD-TIME ONLY. No running services, no network, no health checks.
set -eu

chmod 0755 /usr/lib/aipc/hermes-webui/setup-hermes-webui.sh

# Runtime oneshot that clones/updates the home checkout + enables linger on
# first boot / pin change. enable only (init is not running during build).
systemctl enable aipc-hermes-webui-setup.service

# The user unit auto-enables via the shipped
# /usr/lib/systemd/user/default.target.wants/hermes-webui.service symlink;
# linger (set by the runtime oneshot) makes it start at boot.
