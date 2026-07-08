# Tasks

## 1. Fix root detection

- [ ] 1.1 Add `_resolve_root_device()` to `tools/aipc_lib/storage_reclaim.py`: walk `/sysroot` → `/var` → `/`, first `/dev/*` source, strip btrfs `[subvol]` suffix; return `(device, fstype)`.
- [ ] 1.2 `load_plan` uses `_resolve_root_device()` instead of `findmnt SOURCE /` + `findmnt FSTYPE /`.
- [ ] 1.3 Keep `build_plan` and its `partn == root.partn + 1` guard unchanged; add a comment that the guard assumes AIPC_LIVE immediately after root (per `install-windows-direct`).

## 2. Tests

- [ ] 2.1 Unit test: ostree host — `/sysroot` source `/dev/nvme0n1p9[/root]` resolves to `/dev/nvme0n1p9`, fstype `btrfs`.
- [ ] 2.2 Unit test: plain host — `/` source `/dev/sda2` resolves directly.
- [ ] 2.3 Unit test: composefs at `/` (no `/dev` source) falls through to `/sysroot`.
- [ ] 2.4 Existing planner tests (`test_storage_reclaim.py`) stay green.

## 3. Document

- [ ] 3.1 Note the ostree/composecs root-detection fix in `docs/superpowers/specs/2026-07-07-reclaim-aipc-live-design.md` (or a follow-up note) so the original design record matches the corrected behaviour.
- [ ] 3.2 Static verification: `pytest tools/tests/test_storage_reclaim.py`, `openspec validate reclaim-live-root-detect --strict`.

Not yet hardware-verified for the destructive path (no R6b-after-root host exists yet); dry-run correctness on the current bootc host is the verification target for this change.
