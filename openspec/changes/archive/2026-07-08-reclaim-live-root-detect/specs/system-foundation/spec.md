## ADDED Requirements

### Requirement: Reclaim-Live Detects Root On composefs Hosts

`aipc storage reclaim-live` SHALL resolve the installed system's physical root partition on bootc/composecs hosts by walking `/sysroot` → `/var` → `/`, taking the first mount whose source begins with `/dev/` and stripping any btrfs `[subvolume]` suffix. It SHALL NOT read `findmnt SOURCE /` directly, because on an ostree/composecs deployment `/` is the composefs overlay and `findmnt` returns the literal string `composefs` rather than the backing block device.

#### Scenario: Resolves backing device on a composecs/ostree host

- **WHEN** `aipc storage reclaim-live` runs on a bootc host where `/` is the composefs overlay and the backing btrfs is mounted at `/sysroot` as `/dev/nvme0n1p9[/root]`
- **THEN** the planner resolves root to `/dev/nvme0n1p9` with fstype `btrfs`, instead of exiting with `root partition composefs not found`

#### Scenario: Falls back to /var then / on non-ostree hosts

- **WHEN** the host has no `/sysroot` mount but `/var` (or `/`) is a `/dev/*`-backed mount
- **THEN** the planner resolves root from that mount, so the tool still works on a plain (non-ostree) installed system

#### Scenario: Adjacency guard is unchanged

- **WHEN** root is resolved correctly on an R6b-installed host
- **THEN** the planner still refuses to reclaim unless `AIPC_LIVE` is the partition immediately after root on the same disk — the layout the `install-windows-direct` change produces — and requires the typed confirmation phrase before any destructive step
