"""Unit tests for session registry, internalization filters, classifier rules.

Uses shipped modules under files/usr/lib/aipc-agent (real entry points).
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ship path in-repo
_ROOT = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(_ROOT))


class TestSessionRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["AIPC_SESSION_DIR"] = self._tmpdir.name
        os.environ["AIPC_SESSION_PERSIST"] = "1"
        # Reload so module picks up env
        import aipc_agent.session_registry as sr

        importlib.reload(sr)
        self.sr = sr
        # clear in-memory
        with sr._LOCK:
            sr._SESSIONS.clear()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_open_resume_same_id(self) -> None:
        a = self.sr.open_or_resume("sess-a", source="test", title="查股")
        b = self.sr.open_or_resume("sess-a", source="test")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(a["status"], "active")
        self.assertEqual(b["status"], "active")

    def test_working_then_active_not_done_on_job_finish_touch(self) -> None:
        self.sr.open_or_resume("sess-b", source="test")
        self.sr.bind_job("sess-b", "job123", activity="Hermes 啟動")
        s = self.sr.get("sess-b")
        assert s is not None
        self.assertEqual(s["status"], "working")
        self.assertEqual(s["job_id"], "job123")
        # complete job path: active, clear job — not session done
        self.sr.touch(
            "sess-b", status="active", activity="股價結果…", clear_job=True
        )
        s2 = self.sr.get("sess-b")
        assert s2 is not None
        self.assertEqual(s2["status"], "active")
        self.assertIsNone(s2["job_id"])

    def test_complete_marks_done(self) -> None:
        self.sr.open_or_resume("sess-c", source="test")
        out = self.sr.complete("sess-c", reason="end_session")
        assert out is not None
        self.assertEqual(out["status"], "done")
        # open list excludes done
        open_list = self.sr.list_sessions(include_done=False)
        self.assertFalse(any(x["id"] == "sess-c" for x in open_list))
        # reopen after done creates fresh active
        again = self.sr.open_or_resume("sess-c", source="test")
        self.assertEqual(again["status"], "active")

    def test_activity_snapshot_includes_open(self) -> None:
        self.sr.open_or_resume("sess-d", source="test")
        self.sr.touch("sess-d", status="waiting_user", activity="要查哪支股票？")
        snap = self.sr.activity_snapshot(limit=10)
        ids = [x["id"] for x in snap]
        self.assertIn("sess-d", ids)


class TestMemoryInternalize(unittest.TestCase):
    def test_worth_filter_rejects_noise(self) -> None:
        from aipc_agent import memory

        self.assertFalse(memory._worth_internalizing("你好", "你好"))
        self.assertFalse(memory._worth_internalizing("。", "没听清楚，请再说一次。"))
        self.assertTrue(memory._worth_internalizing("我住在台北", "好的，记住了"))

    def test_agent_lane_isolation(self) -> None:
        from aipc_agent import memory

        self.assertEqual(memory.agent_lane("hermes"), memory.AGENT_HERMES)
        self.assertEqual(memory.agent_lane("daily_assistant"), memory.AGENT_DAILY)
        self.assertNotEqual(
            memory.agent_lane("coder-agentic"), memory.agent_lane("daily")
        )


class TestClassifierDailyNotKeywordOnly(unittest.TestCase):
    def test_daily_phrases_not_rules_hit(self) -> None:
        from aipc_agent.intent_classifier import rules_classify

        # These used to be rules:usage / rules:calendar / rules:search
        for t in (
            "今天有什么会议",
            "搜一下 python 教程",
            "用量还剩多少",
            "查一下邮件",
        ):
            hit = rules_classify(t)
            self.assertIsNone(
                hit,
                f"daily intent must not be keyword-only rules for {t!r}, got {hit}",
            )

    def test_greet_still_rules(self) -> None:
        from aipc_agent.intent_classifier import rules_classify

        hit = rules_classify("你好")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["target"], "respond")
        self.assertEqual(hit["source"], "rules")


class TestStockMultiTurnPlan(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["AIPC_PENDING_DIR"] = self._tmpdir.name
        os.environ["AIPC_PENDING_PERSIST"] = "1"
        import aipc_agent.session_pending as sp

        importlib.reload(sp)
        self.sp = sp
        with sp._LOCK:
            sp._PENDING.clear()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_stock_slot_then_symbol_same_plan_chain(self) -> None:
        from aipc_agent.graphs import plan_dispatch

        sid = "unit-stock-plan"
        self.sp.clear(sid)
        p1 = plan_dispatch("用hermes查股价", sid)
        self.assertEqual(p1.get("target"), "clarify")
        p2 = plan_dispatch("AMD", sid)
        self.assertEqual(p2.get("target"), "hermes")
        orig = str(p2.get("original_text") or "")
        self.assertIn("AMD", orig)

    def test_pending_disk_survives_empty_ram(self) -> None:
        """Multi-worker: stock_slot pending set on worker A, resolve on B."""
        from aipc_agent.graphs import plan_dispatch

        sid = "unit-pending-cross"
        self.sp.clear(sid)
        p1 = plan_dispatch("用hermes查股价", sid)
        self.assertEqual(p1.get("target"), "clarify")
        with self.sp._LOCK:
            self.sp._PENDING.clear()
        # empty RAM → must load from disk
        p2 = plan_dispatch("AMD", sid)
        self.assertEqual(p2.get("target"), "hermes", p2)
        self.assertIn("AMD", str(p2.get("original_text") or ""))


class TestStockDayFollowup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["AIPC_AGENT_CTX_DIR"] = self._tmpdir.name
        os.environ["AIPC_AGENT_CTX_PERSIST"] = "1"
        os.environ["AIPC_PENDING_DIR"] = self._tmpdir.name
        os.environ["AIPC_PENDING_PERSIST"] = "1"
        import aipc_agent.agent_context as ac
        import aipc_agent.session_pending as sp

        importlib.reload(ac)
        importlib.reload(sp)
        self.ac = ac
        self.sp = sp
        with ac._LOCK:
            ac._BUF.clear()
        with sp._LOCK:
            sp._PENDING.clear()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_yesterday_keeps_last_symbol(self) -> None:
        from aipc_agent.graphs import plan_dispatch
        from aipc_agent.memory import AGENT_CHAT

        sid = "unit-stock-day"
        self.sp.clear(sid)
        self.ac.clear(sid)
        self.ac.append_turn(sid, AGENT_CHAT, "user", "查 AMD 股價")
        self.ac.append_turn(
            sid, AGENT_CHAT, "assistant", "AMD 最新股價約 186 美元"
        )
        p = plan_dispatch("那昨天呢", sid)
        self.assertEqual(p.get("target"), "hermes")
        self.assertIn("AMD", str(p.get("original_text") or ""))
        self.assertIn("stock-day", str(p.get("reason") or ""))


class TestAgentContextSTM(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["AIPC_AGENT_CTX_DIR"] = self._tmpdir.name
        os.environ["AIPC_AGENT_CTX_PERSIST"] = "1"
        import aipc_agent.agent_context as ac

        importlib.reload(ac)
        self.ac = ac
        with ac._LOCK:
            ac._BUF.clear()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_stm_append_and_format(self) -> None:
        from aipc_agent.memory import AGENT_CHAT

        sid = "unit-stm"
        self.ac.clear(sid)
        self.ac.append_turn(sid, AGENT_CHAT, "user", "查 AMD 股價")
        self.ac.append_turn(sid, AGENT_CHAT, "assistant", "AMD 約 186 美元")
        hist = self.ac.format_history(sid, AGENT_CHAT)
        self.assertIn("AMD", hist)
        self.ac.clear(sid)
        self.assertEqual(self.ac.format_history(sid, AGENT_CHAT), "")

    def test_stm_disk_survives_empty_process_ram(self) -> None:
        """Models multi-worker: worker-A wrote turns, worker-B has empty RAM.

        Reload + clear in-memory buffer; disk file must still supply history
        so day-followup (那昨天呢) keeps last symbol across uvicorn workers.
        """
        from aipc_agent.memory import AGENT_CHAT

        sid = "unit-stm-cross-proc"
        self.ac.clear(sid)
        self.ac.append_turn(sid, AGENT_CHAT, "user", "查 AMD 股價")
        self.ac.append_turn(
            sid, AGENT_CHAT, "assistant", "AMD 最新股價約 186 美元"
        )
        # Simulate other worker: wipe process-local cache only
        with self.ac._LOCK:
            self.ac._BUF.clear()
        turns = self.ac.get_turns(sid, AGENT_CHAT)
        self.assertTrue(turns, "disk STM must rehydrate after empty RAM")
        blob = " ".join(t.get("content") or "" for t in turns)
        self.assertIn("AMD", blob)
        hist = self.ac.format_history(sid, AGENT_CHAT)
        self.assertIn("AMD", hist)

    def test_history_ignores_none_in_error_blob(self) -> None:
        """Error dumps with 'None' must not become the recovered ticker."""
        from aipc_agent.memory import AGENT_CHAT
        import aipc_agent.session_pending as sp

        importlib.reload(sp)
        sid = "unit-stm-none-junk"
        self.ac.clear(sid)
        self.ac.append_turn(sid, AGENT_CHAT, "user", "查询 AMD 最新股价")
        self.ac.append_turn(
            sid,
            AGENT_CHAT,
            "assistant",
            "API fail Fallbacks=None HTTP 500 model group",
        )
        with self.ac._LOCK:
            self.ac._BUF.clear()
        p = sp.try_continue_stock_from_history(sid, "那昨天呢")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertIn("AMD", str(p.get("original_text") or ""))
        self.assertNotIn("NONE", str(p.get("original_text") or "").upper().replace("AMD", ""))

    def test_farewell_not_stock_history(self) -> None:
        from aipc_agent.memory import AGENT_CHAT
        import aipc_agent.session_pending as sp

        importlib.reload(sp)
        sid = "unit-farewell-stock"
        self.ac.clear(sid)
        self.ac.append_turn(sid, AGENT_CHAT, "user", "查 AMD")
        self.ac.append_turn(sid, AGENT_CHAT, "assistant", "AMD 186 美元")
        p = sp.try_continue_stock_from_history(sid, "没事了")
        self.assertIsNone(p)

    def test_day_followup_after_simulated_worker_switch(self) -> None:
        from aipc_agent.memory import AGENT_CHAT
        import aipc_agent.session_pending as sp

        os.environ["AIPC_PENDING_DIR"] = self._tmpdir.name
        os.environ["AIPC_PENDING_PERSIST"] = "1"
        importlib.reload(sp)
        sid = "unit-stock-day-cross"
        sp.clear(sid)
        self.ac.clear(sid)
        self.ac.append_turn(sid, AGENT_CHAT, "user", "查 AMD 股價")
        self.ac.append_turn(
            sid, AGENT_CHAT, "assistant", "AMD 最新股價約 186 美元"
        )
        # other worker: empty RAM (disk only)
        with self.ac._LOCK:
            self.ac._BUF.clear()
        p = sp.try_continue_stock_from_history(sid, "那昨天呢")
        self.assertIsNotNone(p, "history day-follow must rehydrate STM from disk")
        assert p is not None
        self.assertEqual(p.get("target"), "hermes", p)
        self.assertIn("AMD", str(p.get("original_text") or ""))
        self.assertIn("stock-day", str(p.get("reason") or ""))


if __name__ == "__main__":
    unittest.main()
