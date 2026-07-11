from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "files/usr/lib/aipc-portal"))

from aipc_portal.dashboard import _systemctl_state, compact_idle_snapshot


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

    def test_malformed_manifest_degrades_to_unknown(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        handle.write("models: [")
        handle.close()
        path = Path(handle.name)
        self.addCleanup(path.unlink)

        value = compact_idle_snapshot(
            [], manifest_path=path, now=1000,
            timer_enabled="enabled", timer_active="active",
        )

        self.assertEqual(value["state"], "unknown")
        self.assertIsNone(value["timeout_s"])

    def test_systemctl_execution_failure_degrades_to_unknown(self):
        with mock.patch("aipc_portal.dashboard.subprocess.run", side_effect=OSError):
            self.assertEqual(_systemctl_state("is-active"), "unknown")


class CompactIdleFrontendContractTest(unittest.TestCase):
    def test_runtime_card_formats_observational_states(self):
        source = (ROOT / "web/src/pages/index.astro").read_text(encoding="utf-8")
        for token in (
            "Compact unloaded", "Compact in use", "Compact idle",
            "auto-release", "release in", "compact_idle_release",
        ):
            self.assertIn(token, source)
        self.assertNotIn("/unload", source)


if __name__ == "__main__":
    unittest.main()
