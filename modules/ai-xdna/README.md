# ai-xdna

XDNA 2 NPU kernel driver and userspace management tools for the Ryzen AI
MAX+ 395 NPU. Required before `llm-lemonade` can bind a model to the NPU.

## What it does

- Drops `/etc/modules-load.d/amd-xdna.conf` so `amd_xdna` auto-loads on
  boot.
- Drops `/etc/udev/rules.d/70-amd-xdna.rules` so `/dev/accel/accel0` is
  owned by the `render` group, letting unprivileged containers bind-mount
  it.

No `post-install.sh`, no `modprobe` / `udevadm` calls at build time — those
are no-ops inside a container layer and belong to first boot, which systemd
+ udev handle natively from the dropped files.

## Dependencies

- `system-base` (dkms, kernel-devel — once the package install gap below
  is resolved).
- `system-unified-memory` (NPU visible via lspci).

## Consumers

- `llm-lemonade` (binds `/dev/accel/accel0` into the quadlet).
- `aipc doctor` (calls `xdna-smi`).

## Hardware assumption

XDNA 2 NPU on Ryzen AI MAX+ 395. No assumption about discrete accelerators.

## Status

`.disabled` until an AI PC validates and the package gap is closed.

Gap: `amd-xdna-dkms` and `xdna-smi` are not in the bazzite-dx base repos.
`packages.txt` is intentionally absent — adding the packages back requires
either (a) an out-of-tree repo file in `files/etc/yum.repos.d/` (mirror the
ai-rocm pattern) plus an `rpm-ostree install` in a new `post-install.sh`,
or (b) confirming the AMD upstream kmod ships in a bazzite-dx overlay we
can pull from. Decide on hardware.

Validation on first AI PC boot: (1) `lsmod | grep amd_xdna`, (2)
`/dev/accel/accel0` exists with group `render`, (3) `xdna-smi examine`
enumerates one NPU.
