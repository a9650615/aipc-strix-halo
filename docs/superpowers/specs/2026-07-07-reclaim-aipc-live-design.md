# Reclaim AIPC_LIVE During First Bootstrap

Date: 2026-07-07

## Goal

Add a small first-bootstrap option that lets the user reclaim the Windows-staged `AIPC_LIVE` installer partition into the installed Linux system partition after Bazzite/AIPC has booted from the internal disk.

This is a destructive disk operation, so the default path must be read-only and explicit about what would happen.

## Placement

`install-aipc-linux.sh` guided mode gets a new menu option:

```text
[4] Reclaim AIPC_LIVE into system disk
```

The existing `Start bootstrap` flow does not automatically reclaim disk space. The menu option calls a dedicated `aipc` subcommand instead of embedding partition logic in the bootstrap shell script:

```bash
aipc storage reclaim-live
```

The subcommand defaults to dry-run. A real change requires:

```bash
aipc storage reclaim-live --confirm
```

## Command behavior

`aipc storage reclaim-live` builds a plan from the live machine state and prints:

- the detected `AIPC_LIVE` partition;
- the current `/` source device;
- the parent disk for both devices;
- whether reclaim is allowed;
- the exact destructive steps that would run.

With no `--confirm`, it never runs destructive commands.

With `--confirm`, it prints the same plan and requires the user to type:

```text
reclaim AIPC_LIVE
```

Only then may it delete the partition and grow the installed system partition/filesystem.

## Safety gates

The command refuses to proceed unless all gates pass:

1. `/` resolves to a local block device.
2. Exactly one partition has `LABEL=AIPC_LIVE`.
3. `AIPC_LIVE` and `/` are on the same parent disk.
4. `AIPC_LIVE` is immediately after the installed system partition.
5. The filesystem grow step is one of the supported installed-system paths:
   - Btrfs: `btrfs filesystem resize max /`
   - XFS: `xfs_growfs /`
   - ext4: `resize2fs` on the resolved root block device

If any gate fails, the tool exits non-zero with a one-line reason and prints the current `lsblk` summary for manual recovery.

## Out of scope

The tool does not:

- move partitions;
- merge non-adjacent free space;
- touch Windows partitions;
- auto-run after bootstrap;
- infer a target when multiple `AIPC_LIVE` labels exist.

These cases require manual disk management.

## Implementation shape

Keep the logic small:

- add `aipc storage reclaim-live` to `tools/aipc_lib/cli.py`;
- put planner/executor helpers in one small module, e.g. `tools/aipc_lib/storage_reclaim.py`;
- add the bootstrap menu option in `install-aipc-linux.sh`;
- keep destructive execution behind `--confirm` plus the typed phrase.

The planner should be pure enough to test with fake block-device data. The executor should be thin and only run the planned commands.

## Minimal verification

This is a small safety tool, so do not build a large partition test suite. Verify the important guardrails only:

- fake planner data where `AIPC_LIVE` is absent, duplicated, on another disk, or not adjacent must be refused;
- fake planner data where `AIPC_LIVE` is same-disk and adjacent must produce a reclaim plan;
- CLI dry-run must not call destructive commands;
- `bash -n install-aipc-linux.sh` must pass.

Static verification is enough for implementation review. Actually deleting `AIPC_LIVE` and growing the filesystem is hardware verification and must only happen after the user explicitly asks to run it on the machine.

## Update 2026-07-09 — root detection on ostree/composefs

Safety gate 1 ("`/` resolves to a local block device") was implemented in
`storage_reclaim.py:load_plan` as `findmnt -n -o SOURCE /`, which on an
ostree/composefs (bootc) host returns the literal string `composefs` rather
than the backing block device — so the tool aborted with `root partition
composefs not found` on its own target host. Fixed in commit `9130905`:
`_resolve_root_device()` walks `/sysroot` → `/var` → `/`, takes the first
`/dev/`-backed mount, and strips any btrfs `[subvol]` suffix. The adjacency
guard (gate 4) is unchanged. Tracked in the `reclaim-live-root-detect`
OpenSpec change; the destructive reclaim path remains unverified (no
R6b-after-root host exists yet).
