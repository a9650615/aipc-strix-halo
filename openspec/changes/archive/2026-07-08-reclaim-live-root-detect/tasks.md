# Tasks

## 1. Fix root detection

- [x] 1.1 Add `_resolve_root_device()` to `tools/aipc_lib/storage_reclaim.py`: walk `/sysroot` → `/var` → `/`, first `/dev/*` source, strip btrfs `[subvol]` suffix; return `(device, fstype)`.
- [x] 1.2 `load_plan` uses `_resolve_root_device()` instead of `findmnt SOURCE /` + `findmnt FSTYPE /`.
- [x] 1.3 Keep `build_plan` and its `partn == root.partn + 1` guard unchanged; add a comment that the guard assumes AIPC_LIVE immediately after root (per `install-windows-direct`).

## 2. Tests

- [x] 2.1 Unit test: ostree host — `/sysroot` source `/dev/nvme0n1p9[/root]` resolves to `/dev/nvme0n1p9`, fstype `btrfs`.
- [x] 2.2 Unit test: plain host — `/` source `/dev/sda2` resolves directly.
- [x] 2.3 Unit test: composefs at `/` (no `/dev` source) falls through to `/sysroot`.
- [x] 2.4 Existing planner tests (`test_storage_reclaim.py`) stay green.

## 3. Document

- [x] 3.1 Note the ostree/composecs root-detection fix in `docs/superpowers/specs/2026-07-07-reclaim-aipc-live-design.md` (or a follow-up note) so the original design record matches the corrected behaviour.
- [x] 3.2 Static verification: `pytest tools/tests/test_storage_reclaim.py`, `openspec validate reclaim-live-root-detect --strict`.

Hardware dry-run on the current bootc host verified: `aipc storage reclaim-live` now resolves root (no more `root partition composefs not found`) and is (correctly) refused by the adjacency guard until an R6b-after-root install exists. The destructive reclaim path is not yet hardware-verified — no such host exists yet.
