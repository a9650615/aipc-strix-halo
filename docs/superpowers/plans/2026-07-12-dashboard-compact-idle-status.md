# Dashboard Compact Idle Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the compact model's idle-release timer, residency state, and countdown in the existing Control Center Runtime card.

**Architecture:** The portal backend derives one `runtime.compact_idle_release` object from `models.yaml`, Lemonade's existing loaded-model rows, and systemd timer state. Astro formats that object in the existing Runtime card; the browser never interprets Lemonade's monotonic timestamps.

**Tech Stack:** Python 3 standard library, PyYAML already provided by `system-base`, Astro 5, systemd, unittest.

## Global Constraints

- Keep `/api/v1/dashboard`; do not add an endpoint.
- Do not add manual unload controls or journal history.
- Interpret Lemonade `last_use` as monotonic milliseconds with `time.monotonic()`.
- Missing manifest, model, or timer data degrades only the compact status to `unknown`.
- Preserve unrelated dirty portal work during final integration.
- Both bootc and ansible renders must succeed.

---

## File Map

- Create `modules/system-aipc-portal/tests/test_compact_idle_status.py`: backend state/countdown tests and frontend observational-contract test.
- Modify `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/dashboard.py`: derive compact policy, timer state, and countdown.
- Modify `modules/system-aipc-portal/web/src/pages/index.astro`: format the compact status in the Runtime card.
- Modify `modules/system-aipc-portal/verify.sh`: validate the live dashboard response contains the new object.
- Regenerate `modules/system-aipc-portal/files/usr/lib/aipc-portal/static/index.html` and any Astro-hashed assets changed by the build.
- Modify `modules/system-aipc-portal/README.md`: document the compact status contract.
- Modify `openspec/changes/0009-dashboard-compact-idle-status/tasks.md`: record verified completion.

### Task 1: Backend compact residency snapshot

**Files:**
- Create: `modules/system-aipc-portal/tests/test_compact_idle_status.py`
- Modify: `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/dashboard.py:3-103`

**Interfaces:**
- Produces: `compact_idle_snapshot(models, *, manifest_path=MODEL_MANIFEST, now=None, timer_enabled=None, timer_active=None) -> dict[str, object]`
- Produces in `snapshot()`: `runtime.compact_idle_release`
- Consumes model rows containing `backend`, `model_name`, `status`, and `last_use`.

- [ ] **Step 1: Write the failing backend tests**

Create the test module with these imports and cases:

```python
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "files/usr/lib/aipc-portal"))

from aipc_portal.dashboard import compact_idle_snapshot


class CompactIdleSnapshotTest(unittest.TestCase):
    def manifest(self) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        handle.write(
            "models:\n"
            "  - alias: coder-compact\n"
            "    backend: lemonade\n"
            "    model_id: Compact-Test\n"
            "    idle_unload_after_s: 300\n"
        )
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_unloaded_reports_policy_and_active_timer(self):
        value = compact_idle_snapshot(
            [], manifest_path=self.manifest(), now=1000,
            timer_enabled="enabled", timer_active="active",
        )
        self.assertEqual(value["state"], "unloaded")
        self.assertEqual(value["timer"], "active")
        self.assertEqual(value["timeout_s"], 300)
        self.assertIsNone(value["remaining_s"])

    def test_in_use_has_no_countdown(self):
        value = compact_idle_snapshot(
            [{"backend": "lemonade", "model_name": "Compact-Test",
              "status": "in_use", "last_use": 500_000}],
            manifest_path=self.manifest(), now=1000,
            timer_enabled="enabled", timer_active="active",
        )
        self.assertEqual(value["state"], "in_use")
        self.assertIsNone(value["idle_s"])
        self.assertIsNone(value["remaining_s"])

    def test_idle_uses_monotonic_milliseconds(self):
        value = compact_idle_snapshot(
            [{"backend": "lemonade", "model_name": "Compact-Test",
              "status": "ready", "last_use": 866_000}],
            manifest_path=self.manifest(), now=1000,
            timer_enabled="enabled", timer_active="active",
        )
        self.assertEqual(value["state"], "idle")
        self.assertEqual(value["idle_s"], 134)
        self.assertEqual(value["remaining_s"], 166)

    def test_missing_manifest_degrades_to_unknown(self):
        value = compact_idle_snapshot(
            [], manifest_path=Path("/missing/models.yaml"), now=1000,
            timer_enabled="enabled", timer_active="active",
        )
        self.assertEqual(value["state"], "unknown")
        self.assertIsNone(value["timeout_s"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m unittest modules/system-aipc-portal/tests/test_compact_idle_status.py
```

Expected: import failure because `compact_idle_snapshot` does not exist.

- [ ] **Step 3: Implement the minimal backend helper**

Add `import subprocess`, `import time`, `import yaml`, and:

```python
MODEL_MANIFEST = Path("/etc/aipc/models/models.yaml")
IDLE_RELEASE_TIMER = "aipc-lemonade-idle-release.timer"


def _systemctl_state(command: str) -> str:
    result = subprocess.run(
        ["systemctl", command, IDLE_RELEASE_TIMER],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def compact_idle_snapshot(
    models: list[dict[str, object]],
    *,
    manifest_path: Path = MODEL_MANIFEST,
    now: float | None = None,
    timer_enabled: str | None = None,
    timer_active: str | None = None,
) -> dict[str, object]:
    enabled = timer_enabled if timer_enabled is not None else _systemctl_state("is-enabled")
    active = timer_active if timer_active is not None else _systemctl_state("is-active")
    timer = "active" if enabled == "enabled" and active == "active" else (
        "inactive" if enabled == "enabled" else (
            "disabled" if enabled == "disabled" else "unknown"
        )
    )
    result: dict[str, object] = {
        "model": "coder-compact", "state": "unknown", "timer": timer,
        "timeout_s": None, "idle_s": None, "remaining_s": None,
    }
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        policy = next(
            row for row in manifest.get("models", [])
            if row.get("alias") == "coder-compact"
        )
        model_id = str(policy["model_id"])
        timeout = int(policy["idle_unload_after_s"])
    except (OSError, AttributeError, TypeError, ValueError, KeyError, StopIteration):
        return result
    result["timeout_s"] = timeout
    loaded = next(
        (row for row in models
         if row.get("backend") == "lemonade"
         and row.get("model_name") == model_id),
        None,
    )
    if loaded is None:
        result["state"] = "unloaded"
        return result
    if loaded.get("status") == "in_use":
        result["state"] = "in_use"
        return result
    last_use = loaded.get("last_use")
    if not isinstance(last_use, (int, float)):
        return result
    idle = max(0, int((time.monotonic() if now is None else now) - last_use / 1000))
    result.update(state="idle", idle_s=idle, remaining_s=max(0, timeout - idle))
    return result
```

In `snapshot()`, replace the one-line `runtime` object with:

```python
"runtime": {
    "summary": f"{len(models)} local model(s) loaded",
    "compact_idle_release": compact_idle_snapshot(models),
},
```

- [ ] **Step 4: Run backend tests and verify GREEN**

Run:

```bash
python3 -m unittest modules/system-aipc-portal/tests/test_compact_idle_status.py
python3 -m py_compile modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/dashboard.py
```

Expected: four tests pass and compilation exits 0.

- [ ] **Step 5: Commit the backend slice**

```bash
git add modules/system-aipc-portal/tests/test_compact_idle_status.py \
  modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/dashboard.py
git commit -m "feat(portal): report compact idle release status" \
  -m "Co-authored-by: Codex GPT-5 <noreply@openai.com>" \
  -m "Agent-Role: 副官" \
  -m "Agent-Run: dashboard-compact-idle-status-2026-07-12" \
  -m "Spec-Task: 0009-dashboard-compact-idle-status#1-2"
```

### Task 2: Runtime card presentation

**Files:**
- Modify: `modules/system-aipc-portal/tests/test_compact_idle_status.py`
- Modify: `modules/system-aipc-portal/web/src/pages/index.astro:14-25`
- Regenerate: `modules/system-aipc-portal/files/usr/lib/aipc-portal/static/index.html`
- Regenerate only if the hash changes: `modules/system-aipc-portal/files/usr/lib/aipc-portal/static/_astro/*`

**Interfaces:**
- Consumes: `runtime.compact_idle_release` from Task 1.
- Produces: `compactText(value) -> string` in the page script.

- [ ] **Step 1: Add the failing frontend contract test**

Add to the same test module:

```python
class CompactIdleFrontendContractTest(unittest.TestCase):
    def test_runtime_card_formats_observational_states(self):
        source = (ROOT / "web/src/pages/index.astro").read_text(encoding="utf-8")
        for token in (
            "Compact unloaded", "Compact in use", "Compact idle",
            "auto-release", "release in", "compact_idle_release",
        ):
            self.assertIn(token, source)
        self.assertNotIn("/unload", source)
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest modules/system-aipc-portal/tests/test_compact_idle_status.py
```

Expected: frontend contract fails because the strings are absent.

- [ ] **Step 3: Add the minimal formatter and Runtime text**

Immediately before `refresh()`, add:

```javascript
const duration = (seconds) => {
  if (!Number.isFinite(seconds)) return "unknown";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes}m${rest ? `${rest}s` : ""}` : `${rest}s`;
};
const compactText = (value) => {
  const timer = `timer ${value?.timer || "unknown"}`;
  if (value?.state === "unloaded") return `Compact unloaded · auto-release ${duration(value.timeout_s)} · ${timer}`;
  if (value?.state === "in_use") return `Compact in use · ${timer}`;
  if (value?.state === "idle") return `Compact idle ${duration(value.idle_s)} · release in ${duration(value.remaining_s)} · ${timer}`;
  return `Compact unknown · ${timer}`;
};
```

Replace the Runtime call with:

```javascript
show("ai", `${data.runtime?.summary || "Unavailable"} · ${compactText(data.runtime?.compact_idle_release)}`);
```

- [ ] **Step 4: Run tests and build Astro**

```bash
python3 -m unittest modules/system-aipc-portal/tests/test_compact_idle_status.py
cd modules/system-aipc-portal/web
npm ci
npm run build
cd ..
rm -rf files/usr/lib/aipc-portal/static
cp -a web/dist files/usr/lib/aipc-portal/static
```

Expected: five tests pass; Astro build exits 0; generated `static/index.html`
contains `compact_idle_release`.

- [ ] **Step 5: Commit the frontend slice**

```bash
git add modules/system-aipc-portal/tests/test_compact_idle_status.py \
  modules/system-aipc-portal/web/src/pages/index.astro \
  modules/system-aipc-portal/files/usr/lib/aipc-portal/static
git commit -m "feat(portal): show compact idle countdown" \
  -m "Co-authored-by: Codex GPT-5 <noreply@openai.com>" \
  -m "Agent-Role: 副官" \
  -m "Agent-Run: dashboard-compact-idle-status-2026-07-12" \
  -m "Spec-Task: 0009-dashboard-compact-idle-status#3-5"
```

### Task 3: Verification contract and documentation

**Files:**
- Modify: `modules/system-aipc-portal/verify.sh:21-38`
- Modify: `modules/system-aipc-portal/README.md`
- Modify: `openspec/changes/0009-dashboard-compact-idle-status/tasks.md`

**Interfaces:**
- Consumes: live `GET /api/v1/dashboard`.
- Produces: verification failure `dashboard compact_idle_release missing`.

- [ ] **Step 1: Add the response contract check**

After the existing dashboard curl check in `verify.sh`, add:

```sh
curl -sf http://127.0.0.1:7080/api/v1/dashboard |
  python3 -c 'import json,sys; d=json.load(sys.stdin); x=d.get("runtime", {}).get("compact_idle_release", {}); raise SystemExit(0 if x.get("state") in {"unloaded", "in_use", "idle", "unknown"} and "timer" in x else 1)' \
  || fail "dashboard compact_idle_release missing"
```

- [ ] **Step 2: Document the Runtime card contract**

Add to the Control Center SPA section:

```markdown
The Runtime card also reports `coder-compact` residency and
`aipc-lemonade-idle-release.timer` state. Idle duration and release countdown
are derived server-side from Lemonade's monotonic-millisecond `last_use`;
the card is observational and exposes no unload action.
```

- [ ] **Step 3: Run static and render verification**

```bash
python3 -m unittest modules/system-aipc-portal/tests/test_compact_idle_status.py
modules/system-aipc-portal/verify.sh
npx -y @fission-ai/openspec validate 0009-dashboard-compact-idle-status --strict
PYTHONPATH=tools python3 -m aipc_lib.cli render bootc \
  --image-ref ghcr.io/example/aipc:test --build-date 2026-07-12 \
  --out /tmp/aipc-0009-Containerfile
PYTHONPATH=tools python3 -m aipc_lib.cli render ansible \
  --out /tmp/aipc-0009-site.yml
git diff --check
```

Expected: five tests pass, portal verify exits 0, OpenSpec is valid, both
renders write their output, and diff check is silent.

- [ ] **Step 4: Mark render-complete tasks**

Mark tasks 1-6 complete. Leave hardware verification unchecked until Task 4
proves the live endpoint and UI.

- [ ] **Step 5: Commit verification and docs**

```bash
git add modules/system-aipc-portal/verify.sh \
  modules/system-aipc-portal/README.md \
  openspec/changes/0009-dashboard-compact-idle-status/tasks.md
git commit -m "test(portal): verify compact idle dashboard contract" \
  -m "Co-authored-by: Codex GPT-5 <noreply@openai.com>" \
  -m "Agent-Role: 副官" \
  -m "Agent-Run: dashboard-compact-idle-status-2026-07-12" \
  -m "Spec-Task: 0009-dashboard-compact-idle-status#4-6"
```

### Task 4: Integrate concurrent portal WIP and hardware-verify

**Files:**
- Merge-resolve only: `modules/system-aipc-portal/files/usr/lib/aipc-portal/aipc_portal/dashboard.py`
- Merge-resolve only: `modules/system-aipc-portal/web/src/pages/index.astro`
- Regenerate from combined source: `modules/system-aipc-portal/files/usr/lib/aipc-portal/static/**`
- Modify after proof: `openspec/changes/0009-dashboard-compact-idle-status/tasks.md`

**Interfaces:**
- Consumes the feature branch commits and the main worktree's pre-existing portal WIP.
- Produces a combined main-branch tree and live `/api/v1/dashboard` response.

- [ ] **Step 1: Back up and integrate without losing dirty work**

```bash
git diff --binary --output=/tmp/aipc-pre-0009-merge.patch
git merge --autostash change-0009-dashboard-compact-idle-status
```

If autostash conflicts, preserve both the pre-existing portal behavior and
`compact_idle_release`; confirm no conflict markers, then unstage restored
WIP with `git reset`. Keep the patch until final verification.

- [ ] **Step 2: Rebuild static output from the combined source**

```bash
cd modules/system-aipc-portal/web
npm ci
npm run build
cd ..
rm -rf files/usr/lib/aipc-portal/static
cp -a web/dist files/usr/lib/aipc-portal/static
```

- [ ] **Step 3: Live-hotfix the portal**

Following `docs/live-hotfix-workflow.md`, back up the installed portal
package, install the combined `dashboard.py` and static tree at the path
shown by `systemctl cat aipc-portal.service`, restart only
`aipc-portal.service`, and confirm it becomes active.

- [ ] **Step 4: Verify the live endpoint and UI contract**

```bash
curl -sf http://127.0.0.1:7080/api/v1/dashboard |
  python3 -c 'import json,sys; x=json.load(sys.stdin)["runtime"]["compact_idle_release"]; print(x); assert x["state"] in {"unloaded", "in_use", "idle", "unknown"}; assert x["timer"] == "active"'
curl -sf http://127.0.0.1:7080/ | grep -q compact_idle_release
modules/system-aipc-portal/verify.sh
```

Expected: endpoint reports the real compact state with `timer: active`, the
served page contains the formatter, and portal verification exits 0.

- [ ] **Step 5: Complete hardware task and final verification**

Mark task 7 complete, run all Task 3 Step 3 commands again on the combined
tree, append the same-day agent-log row with the actual verification tiers,
and commit with the required trailers.
