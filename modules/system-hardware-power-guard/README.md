# system-hardware-power-guard

A lightweight hardware safety daemon that prevents battery drain during AC usage by clamping power consumption.

## Overview

When the system is plugged into AC but detects a discharge current (indicating the power supply is insufficient), this module automatically throttles CPU and other components via `sysfs` to ensure the battery does not deplete.

## Features

- **Real-time Monitoring**: Monitors `/sys/class/power_supply/BAT0/current_now`.
- **Auto-Clamping**: Automatically lowers `scaling_max_freq` when power inadequacy is detected.
- **Automatic Recovery**: Restores performance once charging stabilizes.
- **Low Overhead**: Written in Python, designed to run as a minimal background service via Quadlet.

## Dependencies

- `python3`
- `systemd` (via Quadlet)

## Deployment

This module is rendered into the system image using `tools/aipc render bootc` and `tools/aipc render ansible`.
