# How: Resolve the Backing Device, Not the Overlay

The fix is small and confined to `load_plan` in
`tools/aipc_lib/storage_reclaim.py`. `build_plan` is already pure and tested
with fake block-device data; it does not change.

```python
def _resolve_root_device() -> tuple[str, str]:
    for mnt in ("/sysroot", "/var", "/"):
        src = subprocess.check_output(
            ["findmnt", "-n", "-o", "SOURCE", mnt], text=True
        ).strip()
        if src.startswith("/dev/"):
            dev = src.split("[", 1)[0]          # drop btrfs [subvol]
            fstype = subprocess.check_output(
                ["findmnt", "-n", "-o", "FSTYPE", mnt], text=True
            ).strip()
            return dev, fstype
    raise RuntimeError("no block-device backed mount found for root")
```

`load_plan` calls `_resolve_root_device()` instead of querying `/` directly.
`/sysroot` wins on ostree; `/var` covers bazzite's bind layout; `/` is the
fallback for a plain (non-ostree) host.

## Why not also move partitions / handle non-adjacent AIPC_LIVE

Out of scope, same as the original `reclaim-aipc-live` design: the tool does
not move partitions, merge non-adjacent free space, or touch Windows
partitions. Those need manual disk management (or the btrfs-device-add path).
The guard's adjacency requirement is a feature — it refuses unsafe reclaim —
not a bug; the `install-windows-direct` change makes R6b layouts satisfy it.

## Verification

- Static: new unit tests for `_resolve_root_device` covering (a) ostree host
  where `/sysroot` → `/dev/nvme0n1p9[/root]`, (b) plain host where `/` →
  `/dev/sda2`, (c) composefs overlay at `/` with no `/dev` source (must fall
  through to `/sysroot`).
- Existing planner tests stay green unchanged.
- Hardware: on the Strix Halo host, `aipc storage reclaim-live` (dry-run)
  prints a real plan instead of `root partition composefs not found` — though
  the adjacency guard still (correctly) refuses this already-installed host
  until an R6b-after-root install exists.
