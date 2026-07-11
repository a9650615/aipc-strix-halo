"""Persistent job registry: disk store survives restart, subprocess pid/pgid
is recorded on the current job, and orphaned "running" jobs left by a dead
orchestrator are reaped (or safely skipped) on startup."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(_ROOT))


class TestPersistStore(unittest.TestCase):
    def _store(self, tmp_path: Path) -> Path:
        return tmp_path / "task_jobs.json"

    def test_submit_writes_store_and_reload_repopulates(self) -> None:
        import tempfile

        from aipc_agent import task_jobs

        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "task_jobs.json"
            with mock.patch.dict(
                "os.environ", {"AIPC_TASK_JOBS_STORE": str(store)}
            ):

                def fn() -> dict:
                    return {"status": "ok", "text": "done"}

                out = task_jobs.submit(
                    "hermes", "hi", "sess-persist", fn, grace_s=2.0
                )
                self.assertEqual(out.get("status"), "ok")
                self.assertTrue(store.is_file(), "store file should be written")
                on_disk = json.loads(store.read_text(encoding="utf-8"))
                self.assertTrue(on_disk, "store should contain the submitted job")

                # Simulate a fresh process: clear the in-memory cache, reload.
                with task_jobs._JOBS_LOCK:
                    task_jobs._JOBS.clear()
                task_jobs._load_store()
                jobs = task_jobs.job_list(limit=20)
                self.assertTrue(
                    any(j.get("text") == "hi" for j in jobs),
                    "reload should repopulate _JOBS from disk",
                )

    def test_register_proc_records_pid_pgid_on_current_job(self) -> None:
        import os
        import tempfile

        from aipc_agent import task_jobs

        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "task_jobs.json"
            with mock.patch.dict(
                "os.environ", {"AIPC_TASK_JOBS_STORE": str(store)}
            ):
                ready = {}

                def fn() -> dict:
                    ready["job_id"] = task_jobs.current_job_id()
                    task_jobs.register_proc(os.getpid())
                    return {"status": "ok", "text": "done"}

                task_jobs.submit("hermes", "hi", "sess-proc", fn, grace_s=2.0)
                jid = ready.get("job_id")
                self.assertTrue(jid)
                job = task_jobs.job_get(jid)
                self.assertEqual(job.get("pid"), os.getpid())
                self.assertEqual(job.get("pgid"), os.getpgid(os.getpid()))

    def test_register_proc_noop_without_current_job(self) -> None:
        from aipc_agent import task_jobs

        # No current job context — must not raise.
        task_jobs.register_proc(123456)


class TestReapOrphansOnStartup(unittest.TestCase):
    def test_live_non_hermes_pid_is_not_killed_but_marked_interrupted(self) -> None:
        import tempfile

        from aipc_agent import task_jobs

        proc = subprocess.Popen(["sleep", "30"])
        try:
            with tempfile.TemporaryDirectory() as td:
                store = Path(td) / "task_jobs.json"
                with mock.patch.dict(
                    "os.environ", {"AIPC_TASK_JOBS_STORE": str(store)}
                ):
                    with task_jobs._JOBS_LOCK:
                        task_jobs._JOBS.clear()
                        task_jobs._JOBS["job-live"] = {
                            "job_id": "job-live",
                            "worker": "hermes",
                            "status": "running",
                            "started": time.time(),
                            "pid": proc.pid,
                            "pgid": proc.pid,
                        }

                    task_jobs.reap_orphans_on_startup()

                    self.assertIsNone(proc.poll(), "cmdline sanity guard should skip a non-hermes process")
                    job = task_jobs.job_get("job-live")
                    self.assertEqual(job.get("status"), "interrupted")
                    self.assertTrue(job.get("needs_followup"))
                    self.assertIn("中断", job.get("result_text") or "")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def test_dead_pid_marked_interrupted_without_crashing(self) -> None:
        import subprocess as _sp
        import tempfile

        from aipc_agent import task_jobs

        # A pid guaranteed to be dead: spawn and wait for exit.
        dead = _sp.Popen(["true"])
        dead.wait()
        dead_pid = dead.pid

        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "task_jobs.json"
            with mock.patch.dict("os.environ", {"AIPC_TASK_JOBS_STORE": str(store)}):
                with task_jobs._JOBS_LOCK:
                    task_jobs._JOBS.clear()
                    task_jobs._JOBS["job-dead"] = {
                        "job_id": "job-dead",
                        "worker": "hermes",
                        "status": "running",
                        "started": time.time(),
                        "pid": dead_pid,
                        "pgid": dead_pid,
                    }

                task_jobs.reap_orphans_on_startup()

                job = task_jobs.job_get("job-dead")
                self.assertEqual(job.get("status"), "interrupted")
                self.assertTrue(job.get("needs_followup"))


if __name__ == "__main__":
    unittest.main()
