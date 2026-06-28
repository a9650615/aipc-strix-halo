# ai-xdna

XDNA 2 NPU kernel driver and userspace management tools for the Ryzen AI
MAX+ 395 NPU. Required before `llm-lemonade` can bind a model to the NPU.

## What it does

- Installs the `amd-xdna` DKMS kernel module (or prebuilt kmod if available
  for the running kernel).
- Loads `amd_xdna` via modprobe and ensures it autoloads on boot.
- Installs `xdna-smi` for NPU enumeration and health checks.
- Drops a udev rule so `/dev/accel/accel0` is owned by the `render` group,
  letting unprivileged containers bind-mount it.

## Dependencies

- `system-base` (dkms, kernel-devel for the running kernel).
- `system-unified-memory` (NPU visible via lspci).

## Consumers

- `llm-lemonade` (binds `/dev/accel/accel0` into the quadlet).
- `aipc doctor` (calls `xdna-smi`).

## Hardware assumption

XDNA 2 NPU on Ryzen AI MAX+ 395. No assumption about discrete accelerators.
