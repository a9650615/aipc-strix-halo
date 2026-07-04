# Why: Battery Drain on AC (Power Inadequacy)

The system experiences "battery drain while on AC" because the peak power consumption of the SoC (CPU, GPU, NPU) exceeds the capacity of the provided AC adapter. This leads to "power sucking" from the battery, which accelerates battery degradation and causes thermal instability.

# What: Hardware-level Power Capping Module

We will implement a new module `modules/system-power-guard` that acts as a hardware safety limiter. 

## Core Logic
1. **Monitor**: Poll `/sys/class/power_supply/BAT0/current_now` and `status`.
2. **Detect**: If `status == "Charging"` but `current_now < 0` (or indicates discharge) or if a high negative current is detected while on AC, trigger the "Emergency Clamp" mode.
3. **Clamp**: 
    - Lower `cpu_max_freq` via `/sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq`.
    - (If available) Adjust `intel-rapl` or `amd-pstate` power limits to a safe "sustained" wattage.
4. **Recover**: When current stabilizes and indicates proper charging, restore frequencies.

## Changes
- New module: `modules/system-hardware-power-guard`.
- New service: `power-guard.service` (via Quadlet).
- Implementation: A lightweight Python/Bash daemon.

# How: Implementation Plan

1. **Module Structure**: Create the directory structure for `modules/system-hardware-power-guard`.
2. **Detection Script**: Write the core logic in Python to interface with `sysfs`.
3. **Service Deployment**: Create the `.container` or `.service` file via Quadlet to ensure it runs at boot.
4. **Verification**: A test script that simulates a high-load scenario (or modifies sysfs manually) to verify the clamp triggers.

# Tasks
- [ ] Create module directory `modules/system-hardware-power-guard`.
- [ ] Implement core detection and clamping logic (`src/guard_daemon.py`).
- [ ] Create `post-install.sh` for setting up permissions on sysfs nodes.
- [ ] Implement Quadlet unit file for service management.
- [ ] Add `verify.sh` to test the trigger mechanism.
