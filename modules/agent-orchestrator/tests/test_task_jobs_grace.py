"""grace_s auto-detach: fast fn returns inline (no duplicate notify), slow fn
still detaches to the background ack + fires the completion notify once."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(_ROOT))


class TestSubmitGrace(unittest.TestCase):
    def test_fast_fn_delivers_inline_and_suppresses_notify(self) -> None:
        from aipc_agent import activity, task_jobs

        def fast_fn() -> dict:
            return {"status": "ok", "text": "fast reply", "trail": "t1"}

        with mock.patch.object(activity, "complete_notify") as spy:
            out = task_jobs.submit(
                "hermes", "hi", "sess-fast", fast_fn, grace_s=2.0
            )

        self.assertEqual(out.get("status"), "ok")
        self.assertEqual(out.get("text"), "fast reply")
        self.assertEqual(out.get("trail"), "t1")
        # Give the worker's post-return handshake (claim_done) a moment to
        # finish so a wrongly-fired notify would have already happened.
        time.sleep(0.3)
        spy.assert_not_called()

    def test_slow_fn_detaches_and_still_notifies_once(self) -> None:
        from aipc_agent import activity, task_jobs

        def slow_fn() -> dict:
            time.sleep(0.6)
            return {"status": "ok", "text": "slow reply"}

        with mock.patch.object(activity, "complete_notify") as spy:
            out = task_jobs.submit(
                "hermes", "hi", "sess-slow", slow_fn, grace_s=0.2
            )
            self.assertEqual(out.get("status"), "accepted")
            self.assertEqual(out.get("detail"), "background")

            # Worker thread is still running; wait for it to finish and fire
            # the completion notify.
            deadline = time.time() + 3.0
            while spy.call_count == 0 and time.time() < deadline:
                time.sleep(0.05)

        spy.assert_called_once()
        args = spy.call_args.args
        self.assertIn("slow reply", args[2])


if __name__ == "__main__":
    unittest.main()
