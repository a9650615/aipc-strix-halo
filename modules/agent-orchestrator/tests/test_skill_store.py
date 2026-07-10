"""Local skill tree process tests — skills never written under modules/."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(_ROOT))


class TestSkillStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["AIPC_SKILL_ROOT"] = self._tmp.name
        os.environ["AIPC_SKILL_ROOTS"] = self._tmp.name
        import aipc_agent.skill_store as ss

        importlib.reload(ss)
        self.ss = ss

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_match_not_in_modules(self) -> None:
        meta = self.ss.save_skill(
            title="catalog-code-lookup",
            body=(
                "When user gives a catalog code like ABC-123:\n"
                "1. Search the code with web tools\n"
                "2. Prefer primary database sites\n"
                "3. Reply with title, date, cast if found\n"
            ),
            tags=["catalog", "lookup", "code"],
            triggers=["查番号", "catalog code"],
            examples=["帮我查 FNS-232"],
        )
        self.assertIsNotNone(meta)
        assert meta is not None
        path = Path(meta["path"])
        self.assertTrue(path.is_dir())
        self.assertTrue((path / "SKILL.md").is_file())
        self.assertNotIn("modules/", str(path))
        hits = self.ss.match("FNS-232 在哪找", limit=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], meta["id"])
        blob = self.ss.format_for_prompt(hits)
        self.assertIn("catalog", blob.lower() + blob)

    def test_refuse_source_tree_root(self) -> None:
        os.environ["AIPC_SKILL_ROOT"] = str(
            Path(__file__).resolve().parents[3] / "modules" / "agent-orchestrator"
        )
        import aipc_agent.skill_store as ss

        importlib.reload(ss)
        # write_root may create under forbidden — save must refuse if resolved path has markers
        roots = ss.skill_roots()
        # if filter works roots won't include modules path with marker
        for r in roots:
            self.assertNotIn("/modules/agent-orchestrator", str(r))


if __name__ == "__main__":
    unittest.main()
