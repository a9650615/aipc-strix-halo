"""Local skill tree process tests — skills never written under modules/."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

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

    def test_process_teaching_skill_shipped_and_matchable(self) -> None:
        """aipc may ship tool-use teaching skills (no domain answers)."""
        import shutil

        shipped = (
            Path(__file__).resolve().parents[1]
            / "files/usr/share/aipc-agent/skills-process/web-tool-use"
        )
        self.assertTrue((shipped / "SKILL.md").is_file())
        body = (shipped / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("web_search", body)
        self.assertIn("browser", body.lower())
        self.assertNotIn("jav.guru", body)
        self.assertNotIn("javdb", body)
        self.assertNotIn("神喜", body)
        # Copy out of modules/ tree so skill_roots forbid-markers do not apply
        proc = Path(self._tmp.name) / "skills-process"
        shutil.copytree(shipped, proc / "web-tool-use")
        os.environ["AIPC_SKILL_ROOT"] = str(Path(self._tmp.name) / "machine")
        os.environ["AIPC_SKILL_ROOTS"] = (
            f"{Path(self._tmp.name) / 'machine'}:{proc}"
        )
        import aipc_agent.skill_store as ss

        importlib.reload(ss)
        hits = ss.match("look up with web search and browser", limit=3)
        ids = [h.get("id") for h in hits]
        self.assertIn("web-tool-use", ids)
        meta = ss.save_skill(
            title="web-tool-use",
            body="x" * 50 + "\nprocedure tools only\n",
            source="aipc-learn:hermes",
            skill_id="web-tool-use",
        )
        self.assertIsNone(meta)

    def test_save_match_not_in_modules(self) -> None:
        meta = self.ss.save_skill(
            title="product-code-lookup",
            body=(
                "When user gives a product code like ABC-123:\n"
                "1. Search the code with web tools\n"
                "2. Prefer primary result pages\n"
                "3. Reply with title and URL if found\n"
            ),
            tags=["lookup", "code", "web"],
            triggers=["catalog code", "product code"],
            examples=["look up ABC-123"],
        )
        self.assertIsNotNone(meta)
        assert meta is not None
        path = Path(meta["path"])
        self.assertTrue(path.is_dir())
        self.assertTrue((path / "SKILL.md").is_file())
        self.assertNotIn("modules/", str(path))
        hits = self.ss.match("ABC-123 where is it", limit=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], meta["id"])
        blob = self.ss.format_for_prompt(hits)
        self.assertIn("lookup", blob.lower() + blob)

    def test_refuse_source_tree_root(self) -> None:
        os.environ["AIPC_SKILL_ROOT"] = str(
            Path(__file__).resolve().parents[3] / "modules" / "agent-orchestrator"
        )
        import aipc_agent.skill_store as ss

        importlib.reload(ss)
        roots = ss.skill_roots()
        for r in roots:
            self.assertNotIn("/modules/agent-orchestrator", str(r))


class TestSkillLearnQualityGates(unittest.TestCase):
    def test_reject_truncated_not_learned(self) -> None:
        from aipc_agent.skill_learn import _worth_candidate
        from aipc_agent.hermes_bridge import _is_unusable_answer

        bad = "Response truncated due to output length limit"
        self.assertTrue(_is_unusable_answer(bad))
        self.assertFalse(
            _worth_candidate("look up catalog ABC-99", bad, kind="hermes")
        )

    def test_accept_usable_lookup_reply(self) -> None:
        from aipc_agent.skill_learn import _worth_candidate

        good = (
            "ABC-99 title Example; "
            "page https://catalog.example/item/ABC-99"
        )
        trail = "URLS:\n- https://catalog.example/item/ABC-99\n"
        self.assertTrue(
            _worth_candidate(
                "what is catalog ABC-99", good, kind="hermes", trail=trail
            )
        )

    def test_trail_extract_urls_and_tools(self) -> None:
        from aipc_agent.hermes_bridge import _extract_trail

        log = (
            "Calling web_search query=ABC-99\n"
            "browser_navigate https://catalog.example/ABC-99\n"
            "snapshot title=Example Title\n"
            "Session ID: deadbeef01\n"
            "chit chat ignore me\n"
        )
        trail = _extract_trail(log)
        self.assertIn("catalog.example", trail)
        self.assertIn("URLS:", trail)
        self.assertTrue("web_search" in trail or "browser_navigate" in trail)
        self.assertNotIn("chit chat ignore me", trail)

    def test_learn_payload_includes_trail(self) -> None:
        from aipc_agent.skill_learn import _build_learn_payload

        p = _build_learn_payload(
            "look up ABC-99",
            "Title Example; link https://catalog.example/ABC-99",
            kind="hermes",
            agent="hermes",
            trail="URLS:\n- https://catalog.example/ABC-99\nTOOL_LOG:\n- web_search",
        )
        self.assertIn("TOOL_TRAIL", p)
        self.assertIn("catalog.example", p)
        self.assertIn("web_search", p)

    def test_mentor_defaults_strong_with_fallback(self) -> None:
        import aipc_agent.skill_learn as sl

        self.assertTrue(hasattr(sl, "LEARN_MODEL"))
        self.assertTrue(hasattr(sl, "LEARN_FALLBACK_MODEL"))
        src = Path(_ROOT / "aipc_agent" / "skill_learn.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("AIPC_SKILL_LEARN_MODEL", "ornith-35b")', src)
        self.assertIn("assistant-gemma", src)

    def test_learning_features_default_on_in_source(self) -> None:
        root = _ROOT / "aipc_agent"
        skill = (root / "skill_learn.py").read_text(encoding="utf-8")
        queue = (root / "learn_queue.py").read_text(encoding="utf-8")
        browser = (root / "browser_sandbox.py").read_text(encoding="utf-8")
        graphs = (root / "graphs.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("AIPC_SKILL_LEARN", "1")', skill)
        self.assertIn('os.environ.get("AIPC_LEARN_BG", "1")', queue)
        self.assertIn('os.environ.get("AIPC_HERMES_BROWSER", "auto")', browser)
        self.assertIn('os.environ.get("AIPC_HERMES_ROUTE", "1")', graphs)
        conf = (
            Path(__file__).resolve().parents[1]
            / "files/etc/systemd/system/aipc-agent-orchestrator.service.d"
            / "zzz-skill-learn.conf"
        )
        conf_txt = conf.read_text(encoding="utf-8")
        for key in (
            "AIPC_SKILL_LEARN=1",
            "AIPC_LEARN_BG=1",
            "AIPC_HERMES_BROWSER=auto",
            "AIPC_HERMES_ROUTE=1",
            "AIPC_MEM0_INTERNALIZE=1",
            "AIPC_SKILL_LEARN_MODEL=ornith-35b",
        ):
            self.assertIn(key, conf_txt, f"missing default {key}")


class TestLearnPipelineShipped(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["AIPC_SKILL_ROOT"] = self._tmp.name
        os.environ["AIPC_SKILL_ROOTS"] = self._tmp.name
        os.environ["AIPC_SKILL_LEARN"] = "1"
        import aipc_agent.skill_store as ss
        import aipc_agent.skill_learn as sl

        importlib.reload(ss)
        importlib.reload(sl)
        self.ss = ss
        self.sl = sl

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_learn_sync_with_trail_persists_and_match_injects(self) -> None:
        fake = {
            "learn": True,
            "title": "product-code-path",
            "tags": ["lookup", "web"],
            "triggers": ["product code"],
            "body": (
                "1. Use web_search with the code.\n"
                "2. browser_navigate to the item page.\n"
                "3. Extract title and URL from snapshot.\n"
            ),
        }
        hermes_log = (
            "Calling web_search query=ABC-99\n"
            "browser_navigate https://catalog.example/item/ABC-99\n"
            "snapshot ok\n"
        )
        trail = __import__(
            "aipc_agent.hermes_bridge", fromlist=["_extract_trail"]
        )._extract_trail(hermes_log)
        self.assertIn("catalog.example", trail)

        user = "look up catalog ABC-99 title and link"
        reply = (
            "ABC-99 title Example Title; "
            "watch https://catalog.example/watch/ABC-99 ."
        )
        with mock.patch.object(self.sl, "_extract_with_mentor", return_value=fake):
            meta = self.sl._learn_sync(
                user,
                reply,
                session_id="test-sess",
                kind="hermes",
                agent="hermes",
                trail=trail,
            )
        self.assertIsNotNone(meta)
        assert meta is not None
        skill_path = Path(meta["path"])
        self.assertTrue((skill_path / "SKILL.md").is_file())
        self.assertNotIn("/modules/", str(skill_path.resolve()))
        body = (skill_path / "SKILL.md").read_text(encoding="utf-8")
        # path-harvest prefers real hosts from trail
        self.assertIn("catalog.example", body.lower())

        blob = self.sl.skills_for_query("ZZ-1 catalog lookup please", limit=2)
        self.assertTrue(blob)
        self.assertIn("catalog.example", blob.lower())

    def test_enqueue_skill_extract_includes_trail_nonblocking(self) -> None:
        from aipc_agent import learn_queue

        captured: list = []

        def _fake_enqueue(job):
            captured.append(job)
            return True

        with mock.patch.object(learn_queue, "enqueue", side_effect=_fake_enqueue):
            ok = learn_queue.enqueue_skill_extract(
                "user question long enough",
                "assistant reply that is long enough to pass worth gates xxx",
                session_id="s1",
                kind="hermes",
                agent="hermes",
                trail="URLS:\n- https://example.com/x/item",
            )
        self.assertTrue(ok)
        self.assertEqual(len(captured), 1)
        self.assertIn("example.com", captured[0].payload.get("trail", ""))

    def test_dispatch_passes_trail_to_learn_sync(self) -> None:
        from aipc_agent import learn_queue

        seen: dict = {}

        def _fake_learn(user, reply, *, session_id, kind, agent, trail=""):
            seen["trail"] = trail
            return {"id": "x"}

        job = learn_queue.LearnJob(
            kind="skill_extract",
            payload={
                "user": "u",
                "reply": "r",
                "session_id": "s",
                "kind": "hermes",
                "agent": "hermes",
                "trail": "URLS:\n- https://trail.example/p",
            },
        )
        with mock.patch(
            "aipc_agent.skill_learn._learn_sync", side_effect=_fake_learn
        ):
            learn_queue._dispatch(job)
        self.assertIn("trail.example", seen.get("trail", ""))

    def test_maybe_learn_async_enqueues_without_waiting_mentor(self) -> None:
        called = {"n": 0}

        def _slow_learn(*_a, **_k):
            called["n"] += 1
            time.sleep(2.0)
            return None

        t0 = time.monotonic()
        with mock.patch.object(self.sl, "_learn_sync", side_effect=_slow_learn):
            with mock.patch(
                "aipc_agent.learn_queue.enqueue_skill_extract",
                return_value=True,
            ) as enq:
                self.sl.maybe_learn_async(
                    "look up something reusable path please",
                    "here is a long enough success reply with procedure steps 12345",
                    session_id="v",
                    kind="hermes",
                    agent="hermes",
                    trail="URLS:\n- https://x.example/item",
                )
                enq.assert_called_once()
                kwargs = enq.call_args.kwargs
                self.assertIn("x.example", kwargs.get("trail", ""))
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.5, "maybe_learn_async blocked on mentor")
        self.assertEqual(called["n"], 0)


class TestPathHarvestSelfLearn(unittest.TestCase):
    """Trail evidence → PATH skill → next query match. Synthetic hosts only."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["AIPC_SKILL_ROOT"] = self._tmp.name
        os.environ["AIPC_SKILL_ROOTS"] = self._tmp.name
        os.environ["AIPC_SKILL_LEARN"] = "1"
        import aipc_agent.skill_store as ss
        import aipc_agent.skill_learn as sl

        importlib.reload(ss)
        importlib.reload(sl)
        self.ss = ss
        self.sl = sl

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_path_harvest_without_mentor_then_match(self) -> None:
        user = "look up widget ABC-99 details"
        reply = "Found item https://catalog.example/item/ABC-99"
        trail = (
            "URLS:\n"
            "- https://catalog.example/item/ABC-99\n"
            "TOOL_LOG:\n- Calling web_search\n"
        )
        harvested = self.sl.path_skill_from_evidence(user, reply, trail=trail)
        self.assertIsNotNone(harvested)
        assert harvested is not None
        self.assertIn("catalog.example", harvested["body"])
        self.assertEqual(harvested.get("skill_id"), "web-lookup-path")
        self.assertNotIn("番号", harvested.get("triggers") or [])
        self.assertNotIn("A片", harvested.get("triggers") or [])

        with mock.patch.object(self.sl, "_extract_with_mentor", return_value=None):
            meta = self.sl._learn_sync(
                user,
                reply,
                session_id="learn-test",
                kind="hermes",
                agent="hermes",
                trail=trail,
            )
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.get("id"), "web-lookup-path")
        blob = self.sl.skills_for_query("look up ZZ-7 details", limit=2)
        self.assertTrue(blob)
        self.assertIn("catalog.example", blob.lower())

    def test_sidepath_hosts_accumulate_in_skill_tree(self) -> None:
        """Second success merges new host into same skill (no supervisor seed)."""
        r1 = (
            "Part XYZ-10 found on alpha; "
            "details at https://alpha.example/p/XYZ-10 for the catalog entry."
        )
        r2 = (
            "Part XYZ-20 found on beta; "
            "details at https://beta.example/item/XYZ-20 for the catalog entry."
        )
        with mock.patch.object(self.sl, "_extract_with_mentor", return_value=None):
            m1 = self.sl._learn_sync(
                "find part XYZ-10 please",
                r1,
                session_id="s1",
                kind="hermes",
                agent="hermes",
                trail="URLS:\n- https://alpha.example/p/XYZ-10\n",
            )
            m2 = self.sl._learn_sync(
                "find part XYZ-20 please",
                r2,
                session_id="s2",
                kind="hermes",
                agent="hermes",
                trail="URLS:\n- https://beta.example/item/XYZ-20\n",
            )
        self.assertIsNotNone(m1)
        self.assertIsNotNone(m2)
        assert m2 is not None
        self.assertEqual(m2.get("id"), "web-lookup-path")
        body = Path(m2["skill_md"]).read_text(encoding="utf-8")
        self.assertIn("alpha.example", body)
        self.assertIn("beta.example", body)
        # re-harvest must not glue markdown backticks onto URLs
        self.assertNotIn("``", body)
        # next query injects accumulated side paths
        blob = self.sl.skills_for_query("find part QQ-90 please", limit=2)
        self.assertIn("alpha.example", blob)
        self.assertIn("beta.example", blob)
        # respond invent with product code must not be worth learning
        self.assertFalse(
            self.sl._worth_candidate(
                "look up ABC-12 title",
                "Fake invent no link just words about title and cast name here.",
                kind="respond",
                trail="",
            )
        )


class TestUserFeedback(unittest.TestCase):
    def test_negative_feedback_phrases(self) -> None:
        from aipc_agent.feedback import is_negative_feedback, remember_result, apply_negative_feedback
        import tempfile, os
        from pathlib import Path

        self.assertTrue(is_negative_feedback("不对"))
        self.assertTrue(is_negative_feedback("亂答"))
        self.assertTrue(is_negative_feedback("wrong answer"))
        self.assertFalse(is_negative_feedback("帮我查 ABC-12"))
        td = tempfile.mkdtemp()
        os.environ["AIPC_FEEDBACK_DIR"] = td
        import aipc_agent.feedback as fb
        import importlib

        importlib.reload(fb)
        fb.remember_result(
            "s1",
            user="look up X",
            reply="wrong cast name",
            target="hermes",
            trail="URLS:\n- https://a.example/x\n",
            ok=True,
        )
        ack = fb.apply_negative_feedback("s1", "不对")
        self.assertIn("记下", ack)
        self.assertTrue((Path(td) / "last_results.json").is_file())

    def test_feedback_cross_session_krunner_to_voice(self) -> None:
        """krunner answer must be feedbackable from voice session_id."""
        import tempfile
        import os
        import importlib
        from pathlib import Path
        from aipc_agent import feedback as fb

        td = tempfile.mkdtemp()
        os.environ["AIPC_FEEDBACK_DIR"] = td
        importlib.reload(fb)
        fb.remember_result(
            "krunner",
            user="查 CLUB-915",
            reply="假演员名单",
            target="hermes",
            ok=True,
        )
        # different channel says 不对
        last = fb.get_last("voice-assistant")
        self.assertIsNotNone(last)
        self.assertIn("假演员", last.get("reply") or "")
        ack = fb.apply_negative_feedback("voice-assistant", "不对")
        self.assertIn("记下", ack)
        data = __import__("json").loads((Path(td) / "last_results.json").read_text())
        self.assertEqual(data["krunner"].get("feedback"), "negative")


class TestHermesTrailFromSessionDb(unittest.TestCase):
    """Quiet mode leaves no tool stdout — trail must come from state.db."""

    def test_trail_from_session_db_extracts_urls_and_tools(self) -> None:
        import sqlite3
        import tempfile
        from pathlib import Path

        from aipc_agent.hermes_bridge import (
            _collect_trail,
            _trail_from_session_db,
        )

        tmp = Path(tempfile.mkdtemp())
        hermes = tmp / ".hermes"
        hermes.mkdir()
        db = hermes / "state.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                role TEXT,
                content TEXT,
                tool_call_id TEXT,
                tool_calls TEXT,
                tool_name TEXT,
                timestamp REAL
            );
            """
        )
        sid = "20260710_test_session"
        conn.execute(
            "INSERT INTO messages(session_id, role, content, tool_calls, tool_name, timestamp) "
            "VALUES (?,?,?,?,?,1)",
            (
                sid,
                "assistant",
                None,
                '[{"function":{"name":"browser_navigate","arguments":"{\\"url\\":\\"https://catalog.example/item/ABC-99\\"}"}}]',
                None,
            ),
        )
        conn.execute(
            "INSERT INTO messages(session_id, role, content, tool_calls, tool_name, timestamp) "
            "VALUES (?,?,?,?,?,2)",
            (sid, "tool", '{"ok":true,"url":"https://catalog.example/item/ABC-99"}', None, "browser_navigate"),
        )
        conn.commit()
        conn.close()

        trail = _trail_from_session_db(str(tmp), sid)
        self.assertIn("catalog.example", trail)
        self.assertIn("browser_navigate", trail.lower())
        # quiet stdout empty still yields trail via collect
        collected = _collect_trail(
            str(tmp),
            stdout="final answer only\nSession ID: " + sid + "\n",
            stderr="",
            session_id=sid,
        )
        self.assertIn("catalog.example", collected)


class TestWebHintMultiEngine(unittest.TestCase):
    def test_format_and_rank_prefer_code_urls(self) -> None:
        from aipc_agent import web_hint

        hits = [
            {
                "title": "unrelated",
                "url": "https://example.com/other",
                "snippet": "",
                "engine": "bing",
            },
            {
                "title": "ABC-99 Item",
                "url": "https://catalog.example/item/abc-99",
                "snippet": "",
                "engine": "brave",
            },
        ]
        ranked = web_hint._rank_hits(hits, "ABC-99")
        self.assertIn("abc-99", ranked[0]["url"].lower())
        blob = web_hint.format_hints(ranked)
        self.assertIn("Multi-engine", blob)
        self.assertTrue(web_hint.hermes_hint_enabled())

    def test_junk_urls_filtered(self) -> None:
        from aipc_agent.web_hint import _is_junk_url

        self.assertTrue(_is_junk_url("https://hackerone.com/brave"))
        self.assertTrue(_is_junk_url("https://search.brave.com/search?q=x"))
        self.assertFalse(_is_junk_url("https://catalog.example/item/x"))


class TestGroundingAntiInvent(unittest.TestCase):
    """Structural grounding — synthetic invents vs URL-backed replies."""

    def test_product_code_needs_tools(self) -> None:
        from aipc_agent.grounding import needs_tool_lookup, extract_product_codes

        self.assertTrue(needs_tool_lookup("look up SKU ABC-99 title"))
        self.assertIn("ABC-99", extract_product_codes("ABC-99 details"))
        self.assertFalse(needs_tool_lookup("hello how is the weather"))

    def test_reject_ungrounded_invent(self) -> None:
        from aipc_agent.grounding import (
            is_ungrounded_lookup,
            should_learn,
            has_tool_grounding,
        )

        user = "look up ABC-99 cast and title"
        fake = (
            "According to my database ABC-99 stars Fake Person. "
            "See https://www.fanza.com/ only."
        )
        self.assertTrue(is_ungrounded_lookup(user, fake, trail=""))
        self.assertFalse(should_learn(user, fake, kind="respond", trail=""))
        self.assertFalse(has_tool_grounding(reply=fake, trail=""))

    def test_accept_grounded_item_url(self) -> None:
        from aipc_agent.grounding import is_ungrounded_lookup, should_learn

        user = "look up ABC-99 title and link"
        good = (
            "ABC-99 title Example Widget; "
            "page https://catalog.example/item/ABC-99"
        )
        trail = (
            "URLS:\n- https://catalog.example/item/ABC-99\n"
            "TOOL_LOG:\n- Calling web_search query=ABC-99\n"
        )
        self.assertFalse(is_ungrounded_lookup(user, good, trail=trail))
        self.assertTrue(should_learn(user, good, kind="hermes", trail=trail))
        wrong = "ABC-99 is made up with no link."
        self.assertTrue(is_ungrounded_lookup(user, wrong, trail=""))
        self.assertFalse(should_learn(user, wrong, kind="hermes", trail=""))

    def test_worth_candidate_blocks_respond_invent(self) -> None:
        from aipc_agent.skill_learn import _worth_candidate

        user = "look up ABC-99 title and link"
        fake = (
            "According to records ABC-99 is a pure theme title. "
            "Search the official store homepage."
        )
        self.assertFalse(
            _worth_candidate(user, fake, kind="respond", trail="")
        )


class TestBrowserNoTopicGate(unittest.TestCase):
    def test_needs_browser_is_env_policy(self) -> None:
        import aipc_agent.browser_sandbox as bs

        with mock.patch.object(bs, "MODE", "off"):
            self.assertFalse(bs.needs_browser("lookup ABC-99 online"))
            self.assertFalse(bs.needs_browser("search watch link http://x"))
        with mock.patch.object(bs, "MODE", "auto"):
            self.assertTrue(bs.needs_browser("hello task"))
            self.assertFalse(bs.needs_browser("   "))
            self.assertTrue(bs.needs_browser("", long_task=True))
        with mock.patch.object(bs, "MODE", "always"):
            self.assertTrue(bs.needs_browser(""))

    def test_no_topic_allowlist_in_process(self) -> None:
        root = _ROOT / "aipc_agent"
        for name in ("browser_sandbox.py", "web_hint.py", "grounding.py", "skill_learn.py"):
            src = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("def lookup_wants_web", src)
            self.assertNotIn('"A片"', src)
            self.assertNotIn('("查",', src)
            self.assertNotIn('("搜",', src)
            self.assertNotIn("jav.guru", src)
            self.assertNotIn("javdb", src)


if __name__ == "__main__":
    unittest.main()
