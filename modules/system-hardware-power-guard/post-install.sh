#!/bin/bash
# post-install.sh for system-hardware-power-guard

set -e

echo "Setting up permissions for power-guard sysfs access..."

# In a real deployment, we'd ensure the user running the daemon
# has write access to /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq
# For now, we assume the service runs as root via Quadlet.

echo "Power guard setup complete."
