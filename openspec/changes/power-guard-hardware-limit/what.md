# What: Hardware-level Power Capping Module

The `system-hardware-power-guard` module implements a low-latency, hardware-centric mechanism to prevent battery drain when the AC adapter is insufficient for the current workload. 

It focuses exclusively on **clamping power consumption** at the kernel/driver level (via sysfs) rather than high-level application orchestration.

## Components
1. **Detection Engine**: Monitors `current_now` and `status` from `/sys/class/power_supply/BAT0/`.
2. **Policy Engine**: Defines "Safe" vs "Clamp" thresholds for wattage/amperage.
3. **Enforcer**: Interacts with `cpufreq`, `intel-rapl`/`amd-pstate`, and potentially GPU power limits to apply frequency or wattage caps.

## Specification Diffs (Targeting Modules)
This change introduces a completely new module: `modules/system-hardware-power-guard`. It does not modify existing modules but adds a new layer of system stability.
