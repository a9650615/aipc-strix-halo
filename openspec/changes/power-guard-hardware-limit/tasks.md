# Tasks for power-guard-hardware-limit

- [ ] Create module directory `modules/system-hardware-power-guard`
- [ ] Implement core detection and clamping logic (`modules/system-hardware-power-guard/files/src/guard_daemon.py`)
- [ ] Create `post-install.sh` for setting up permissions on sysfs nodes
- [ ] Implement Quadlet unit file for service management (`modules/system-hardware-power-guard/files/quadlet/power-guard.container`)
- [ ] Add `verify.sh` to test the trigger mechanism via sysfs emulation
- [ ] Update module `README.md` with usage and configuration details
