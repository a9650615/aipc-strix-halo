# How: Implementation Details for Hardware Power Guard

The implementation will focus on a lightweight, high-reliability daemon that interacts directly with the Linux kernel's `sysfs` interfaces.

## 1. Core Logic (Python Daemon)

We will use Python for the daemon because of its excellent handling of file I/O and ability to handle sub-processes if needed (e.g., calling `cpupower`).

**Algorithm:**
1. **Loop**: Every 2 seconds, read `/sys/class/power_supply/BAT0/status` and `/sys/class/power_supply/BAT0/current_now`.
2. **State Check**:
   - IF `status == 'Charging'` AND `current_now < threshold_drain` (where `threshold_drain` is a negative value indicating discharge):
     - Trigger `enter_clamp_mode()`.
   - ELSE IF `status == 'Charging'` AND `current_now >= threshold_drain`:
     - Trigger `exit_clamp_mode()`.
3. **Clamping Action (`enter_clamp_mode`)**:
   - Iterate through `/sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq` and set it to a predefined "Safe Limit" (e.g., 50% of max).
   - (If `intel-rapl` or similar driver is present) Cap the `max_power_limit`.
4. **Recovery Action (`exit_clamp_mode`)**:
   - Restore `scaling_max_freq` to its original value (stored during entry).

## 2. Deployment via Quadlet

The daemon will be packaged as a `.container` or `.service` unit using the Quadlet mechanism, ensuring it is managed by `systemd` and starts automatically with the OS.

## 3. Module Structure
```
modules/system-hardware-power-guard/
├── README.md               # Module overview and dependencies
├── packages.txt            # Dependencies for the module
├── files/                  # The actual daemon code and config
│   ├── src/
│   │   └── guard_daemon.py # The core logic
│   └── quadlet/
│       └── power-guard.container # Quadlet unit file
├── post-install.sh         # Setup permissions/directories
└── verify.sh               # Hardware-emulated testing script
```
