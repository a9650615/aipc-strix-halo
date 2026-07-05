#!/bin/sh
# post-install.sh — system-asus-input
# BUILD-TIME ONLY.
set -eu

# Ensure asus-wmi is loaded (if possible)
modprobe asus-wmi || true
