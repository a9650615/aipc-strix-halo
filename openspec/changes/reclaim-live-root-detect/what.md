# What: Detect the Real Root Partition on ostree/composefs

`aipc storage reclaim-live` SHALL resolve the installed system's **physical**
root partition correctly on bootc/composecs hosts, and its planner SHALL match
the layout the install flow actually produces (AIPC_LIVE after root, per the
`install-windows-direct` change).

## Behaviour changes

- `load_plan` no longer reads `findmnt SOURCE /` (composefs overlay). It
  resolves the backing btrfs/ext4/xfs partition by inspecting `/sysroot` first
  (where ostree mounts the real device), falling back to `/var`, then `/`,
  and strips any btrfs `[subvolume]` suffix to recover the bare block device
  (e.g. `/dev/nvme0n1p9[/root]` → `/dev/nvme0n1p9`).
- The filesystem type is read from the same resolved mount, not from `/`.
- The adjacency guard and destructive steps are otherwise unchanged — they
  were correct for the intended layout; only root detection was broken.

## Capabilities

- Modifies capability: `system-foundation` (the `aipc storage reclaim-live`
  helper's root-detection contract).
- Depends on `install-windows-direct`'s AIPC_LIVE-after-root layout for the
  guard to ever pass on R6b hosts.

## Specification Diffs (Targeting Modules)

`tools/aipc_lib/storage_reclaim.py`:
- `load_plan` root resolution: walk `/sysroot` → `/var` → `/`, take the first
  `findmnt SOURCE` beginning with `/dev/`, strip the `[...]` subvolume suffix.
- fstype sourced from the same mount point.
- `build_plan`'s existing `partn == root.partn + 1` adjacency rule is
  retained and documented as depending on the install layout placing
  AIPC_LIVE immediately after root (no `/boot` wedged between).
