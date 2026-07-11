"""Session-bound proactive followup: a finished/interrupted job owed a
mention to the user is surfaced exactly once, scoped to the session that
started it, and never for a job already delivered inline within grace_s."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(_ROOT))


class TestTakePendingFollowups(unittest.TestCase):
    def _isolated_store(self):
        td = tempfile.TemporaryDirectory()
        store = Path(td.name) / "task_jobs.json"
        patch = mock.patch.dict("os.environ", {"AIPC_TASK_JOBS_STORE": str(store)})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(td.cleanup)
        from aipc_agent import task_jobs

        with task_jobs._JOBS_LOCK:
            task_jobs._JOBS.clear()
        return task_jobs

    def test_finished_job_surfaced_once_then_acknowledged(self) -> None:
        task_jobs = self._isolated_store()
        with task_jobs._JOBS_LOCK:
            task_jobs._JOBS["j1"] = {
                "job_id": "j1",
                "session_id": "s1",
                "status": "ok",
                "result_status": "ok",
                "plan_summary": "整理下週行程",
                "needs_followup": True,
            }

        first = task_jobs.take_pending_followups("s1")
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["job_id"], "j1")

        second = task_jobs.take_pending_followups("s1")
        self.assertEqual(second, [])

    def test_other_session_not_returned(self) -> None:
        task_jobs = self._isolated_store()
        with task_jobs._JOBS_LOCK:
            task_jobs._JOBS["j2"] = {
                "job_id": "j2",
                "session_id": "s2",
                "status": "ok",
                "result_status": "ok",
                "plan_summary": "x",
                "needs_followup": True,
            }

        self.assertEqual(task_jobs.take_pending_followups("s1"), [])
        # Untouched — still claimable by its own session.
        mine = task_jobs.take_pending_followups("s2")
        self.assertEqual(len(mine), 1)

    def test_followup_notice_renders_short_nonempty_text(self) -> None:
        task_jobs = self._isolated_store()
        for status in ("ok", "error", "interrupted"):
            job = {
                "job_id": "j",
                "session_id": "s1",
                "status": status,
                "result_status": status,
                "plan_summary": "写周报",
            }
            notice = task_jobs.followup_notice([job])
            self.assertTrue(notice)
            self.assertLess(len(notice), 120)

        self.assertEqual(task_jobs.followup_notice([]), "")

    def test_delivered_inline_job_gets_no_followup(self) -> None:
        task_jobs = self._isolated_store()

        def fast_fn() -> dict:
            return {"status": "ok", "text": "fast reply"}

        out = task_jobs.submit("hermes", "hi", "sess-inline", fast_fn, grace_s=2.0)
        self.assertEqual(out.get("status"), "ok")

        # Grace-delivered result is spoken synchronously; nothing owed.
        deadline = time.time() + 2.0
        job_id = None
        while time.time() < deadline:
            with task_jobs._JOBS_LOCK:
                for jid, j in task_jobs._JOBS.items():
                    if j.get("session_id") == "sess-inline":
                        job_id = jid
            if job_id:
                break
            time.sleep(0.02)
        self.assertIsNotNone(job_id)
        job = task_jobs.job_get(job_id)
        self.assertTrue(job.get("delivered_inline"))
        self.assertFalse(job.get("needs_followup"))
        self.assertEqual(task_jobs.take_pending_followups("sess-inline"), [])

    def test_background_finish_without_grace_owes_a_followup(self) -> None:
        task_jobs = self._isolated_store()

        def fn() -> dict:
            return {"status": "ok", "text": "done"}

        out = task_jobs.submit("hermes", "hi", "sess-bg", fn)
        self.assertEqual(out.get("status"), "accepted")

        deadline = time.time() + 2.0
        job = None
        while time.time() < deadline:
            jobs = [j for j in task_jobs.job_list(limit=20) if j.get("session_id") == "sess-bg"]
            if jobs and jobs[0].get("status") != "running":
                job = jobs[0]
                break
            time.sleep(0.02)
        self.assertIsNotNone(job)
        self.assertTrue(job.get("needs_followup"))
        pending = task_jobs.take_pending_followups("sess-bg")
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
