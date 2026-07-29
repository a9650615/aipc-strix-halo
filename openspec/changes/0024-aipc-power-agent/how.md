# how — 0024-aipc-power-agent

1. Expand module `system-hardware-power-guard` (no new module category).
2. Port `power_guard.py` → `backfeed.py` with identical step semantics.
3. Port live `/usr/local/sbin/aipc-usbc-core-policy.py` → `core_parking.py`
   (class + dry_run + kill switch).
4. `agent.py` loads nested YAML (legacy flat → backfeed + default core_parking).
5. On SIGTERM: backfeed releases clamps; core_parking restores all CPUs.
6. Tests: existing charge-cap tests retargeted; new core_parking + config tests.
7. Live deploy (separate from this change): disable old units, install files,
   enable `aipc-power-agent` — see `docs/live-hotfix-workflow.md`.
