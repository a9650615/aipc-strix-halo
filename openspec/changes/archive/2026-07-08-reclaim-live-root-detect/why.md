# Why: `aipc storage reclaim-live` Cannot Run On Its Own Target Host

`aipc storage reclaim-live` was built to reclaim the Windows-staged
`AIPC_LIVE` installer partition into the installed Linux root after first
boot. On the physical Strix Halo AI PC (2026-07-09) it **does not run at all**:
a dry-run prints `root partition composefs not found` and exits non-zero.

Two defects, both hardware-observed on this bootc/composecs host:

1. **Root detection assumes a plain block device.** `load_plan` resolves the
   root partition with `findmnt -n -o SOURCE /`. On an ostree/composecs
   deployment `/` is the composefs overlay, so `findmnt` returns the literal
   string `composefs` — not `/dev/nvme0n1p9`. The planner then finds no
   matching partition and refuses. The tool's own target platform is the one
   it cannot detect root on.

2. **The adjacency guard is asserted against the R6b layout that produced it.**
   The guard requires `AIPC_LIVE.partn == root.partn + 1` (AIPC_LIVE
   immediately *after* root). But the R6b Windows-direct runbook creates
   AIPC_LIVE *before* the bazzite install region, so on any host installed via
   R6b, AIPC_LIVE sits physically **before** root — the guard can never pass
   even if defect 1 is fixed. The tool and the install flow disagree about
   where AIPC_LIVE ends up.

Defect 2 is closed by the companion change `install-windows-direct` (AIPC_LIVE
placed *after* root). This change closes defect 1 and pins the guard's
expectation to the corrected layout.
