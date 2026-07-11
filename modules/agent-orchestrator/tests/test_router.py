"""Slice A/B router: schemas, analyze, shadow, tts, spoken, quality, subscription, anti-cases."""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(_ROOT))


class TestRouterSchemas(unittest.TestCase):
    def test_envelope_roundtrip(self) -> None:
        from aipc_agent.router.envelope import build_envelope
        from aipc_agent.router.schemas import validate_envelope

        env = build_envelope("你好", session_id="voice-assistant", source="voice")
        validate_envelope(env)
        self.assertEqual(env["tts_owner"], "voice_client")
        self.assertEqual(env["paid_policy"], "deny")
        self.assertIn("prompt", env["data_scopes"])

    def test_krunner_tts_owner(self) -> None:
        from aipc_agent.router.tts_owner import speak_owner_for

        self.assertEqual(speak_owner_for("krunner", "krunner"), "krunner")
        self.assertEqual(speak_owner_for("api", "default"), "agent")
        self.assertEqual(speak_owner_for("voice", "x"), "voice_client")


class TestAnalyze(unittest.TestCase):
    def test_usage_not_chat(self) -> None:
        from aipc_agent.router.analyze import analyze
        from aipc_agent.router.envelope import build_envelope

        a = analyze(build_envelope("查一下用量", session_id="voice-assistant", source="voice"))
        self.assertIn("usage_tools", a["required"])
        self.assertEqual(a["request_class"], "L2")

    def test_live_stock_grounding(self) -> None:
        from aipc_agent.router.analyze import analyze
        from aipc_agent.router.envelope import build_envelope

        a = analyze(build_envelope("今天 AMD 股价", source="api"))
        self.assertIn("grounding", a["required"])
        self.assertEqual(a["freshness"], "live")

    def test_greet_l0(self) -> None:
        from aipc_agent.router.analyze import analyze
        from aipc_agent.router.envelope import build_envelope

        a = analyze(build_envelope("你好", source="voice", session_id="voice-assistant"))
        self.assertEqual(a["request_class"], "L0")
        self.assertIn("deterministic_local", a["required"])

    def test_explicit_provider_recorded(self) -> None:
        from aipc_agent.router.analyze import analyze
        from aipc_agent.router.envelope import build_envelope

        a = analyze(build_envelope("用 Claude 写个排序", source="api"))
        self.assertEqual(a["explicit_provider"], "claude-subscription")

    def test_codex_override(self) -> None:
        from aipc_agent.router.analyze import analyze
        from aipc_agent.router.envelope import build_envelope

        a = analyze(build_envelope("用 Codex 改这个 bug", source="api"))
        self.assertEqual(a["explicit_provider"], "codex-subscription")

    def test_grok_override(self) -> None:
        from aipc_agent.router.analyze import analyze
        from aipc_agent.router.envelope import build_envelope

        a = analyze(build_envelope("叫 Grok 改這個 bug", source="api"))
        self.assertEqual(a["explicit_provider"], "grok-subscription")

    def test_no_topic_refusal_fields(self) -> None:
        from aipc_agent.router.analyze import analyze
        from aipc_agent.router.envelope import build_envelope

        a = analyze(build_envelope("讲个成人笑话", source="api"))
        self.assertNotIn("refused", a)
        self.assertIn("required", a)
        self.assertTrue(a["required"])


class TestSpokenAndQuality(unittest.TestCase):
    def test_spoken_shorter_than_full(self) -> None:
        from aipc_agent.router.spoken import package_result, spoken_summary

        full = "第一句很长很长。" * 20 + "第二句也是。" * 10 + "第三句结束。"
        pkg = package_result(full)
        self.assertEqual(pkg["full_text"], full.strip())
        self.assertEqual(pkg["text"], full.strip())
        self.assertLessEqual(len(pkg["spoken_summary"]), 160)
        self.assertLess(len(pkg["spoken_summary"]), len(full))
        # spoken_summary helper agrees
        self.assertEqual(pkg["spoken_summary"], spoken_summary(full))

    def test_quality_empty_fails(self) -> None:
        from aipc_agent.router.quality import structural_gate

        g = structural_gate(reply="", required=["chat"])
        self.assertFalse(g["ok"])

    def test_quality_ungrounded_live(self) -> None:
        from aipc_agent.router.quality import structural_gate

        g = structural_gate(
            reply="今天台风很强，别出门。",
            required=["grounding", "web_search"],
            freshness="live",
            trail="",
        )
        self.assertIn("ungrounded_live", g["reasons"])


class TestShadowAndAuthoritative(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        os.environ["AIPC_AGENT_ROUTING_POLICY"] = str(
            Path(__file__).resolve().parents[1]
            / "files"
            / "etc"
            / "aipc"
            / "agent"
            / "routing-policy.yaml"
        )
        os.environ["AIPC_ROUTER_TRACE_DIR"] = self._td.name
        os.environ["AIPC_ROUTER_SHADOW"] = "1"
        os.environ["AIPC_ROUTER_TRACE"] = "1"
        import aipc_agent.router.trace as tr
        import aipc_agent.router.shadow as sh
        import aipc_agent.router.policy as pol

        importlib.reload(tr)
        importlib.reload(pol)
        importlib.reload(sh)
        self.tr = tr
        self.sh = sh

    def tearDown(self) -> None:
        self._td.cleanup()
        os.environ.pop("AIPC_ROUTER_TRACE_DIR", None)
        os.environ.pop("AIPC_ROUTER_AUTHORITATIVE", None)
        os.environ.pop("AIPC_AGENT_ROUTING_POLICY", None)

    def test_shadow_agrees_usage(self) -> None:
        dec = self.sh.plan_shadow(
            "查一下用量",
            session_id="voice-assistant",
            source="voice",
            live_plan={"target": "daily_assistant", "mode": "short"},
        )
        self.assertEqual(dec["shadow_target"], "daily_assistant")
        self.assertTrue(dec["agree"])
        self.assertTrue(dec["paid_allowed"])
        self.assertNotEqual(dec["shadow_target"], "subscription")

    def test_observe_writes_trace_no_raw_text(self) -> None:
        dec = self.sh.observe_and_trace(
            "今天台风动态",
            session_id="voice-assistant",
            source="voice",
            live_plan={"target": "hermes", "mode": "short"},
        )
        self.assertIsNotNone(dec)
        path = Path(self._td.name) / "routes.jsonl"
        self.assertTrue(path.is_file())
        line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
        obj = json.loads(line)
        self.assertNotIn("text", obj)
        self.assertIn("text_hash", obj)
        self.assertEqual(obj["result"], "shadow")
        self.assertIn(obj["shadow_target"], ("hermes", "daily_assistant"))

    def test_confirmed_subscription_slice_b(self) -> None:
        from aipc_agent.router.policy import load_policy

        pol = load_policy()
        self.assertTrue(pol.get("paid_enabled"))
        self.assertFalse(pol.get("metered_enabled"))
        self.assertEqual(pol.get("subscription_ask_scope"), "task")
        self.assertEqual(str(pol.get("slice") or "A").upper(), "B")

    def test_authoritative_plan_usage(self) -> None:
        from aipc_agent.router.decide import plan_authoritative

        p = plan_authoritative("查一下用量", session_id="voice-assistant", source="voice")
        self.assertEqual(p["target"], "daily_assistant")
        self.assertEqual(p["source"], "router")
        self.assertIn("usage_tools", p.get("required") or [])

    def test_authoritative_no_hermes_phrase_needed(self) -> None:
        from aipc_agent.router.decide import plan_authoritative

        p = plan_authoritative("帮我写一个快速排序", session_id="s", source="api")
        self.assertIn(p["target"], ("hermes", "coder"))


class TestClientOwnsTts(unittest.TestCase):
    def test_tts_owner_client_paths(self) -> None:
        from aipc_agent.router.tts_owner import speak_owner_for

        # Same contract graphs._client_owns_tts uses (without importing langchain)
        self.assertEqual(speak_owner_for("", "voice-assistant"), "voice_client")
        self.assertEqual(speak_owner_for("krunner", "krunner"), "krunner")
        self.assertEqual(speak_owner_for("api", "default"), "agent")
        self.assertIn(
            speak_owner_for("", "voice-assistant"),
            ("voice_client", "krunner"),
        )


class TestSubscriptionAdapter(unittest.TestCase):
    def test_feature_detect_and_dry_run(self) -> None:
        from aipc_agent.router import subscription as sub

        fd = sub.feature_detect()
        self.assertIn("codex", fd)
        self.assertIn("claude", fd)
        self.assertFalse(fd["metered_enabled"])
        self.assertFalse(fd["auto_escalation"])
        events = list(sub.run_codex_exec("hi", dry_run=True))
        types = [e["type"] for e in events]
        self.assertIn("accepted", types)
        self.assertIn("result", types)
        grok_events = list(sub.run_grok_cli("hi", dry_run=True))
        self.assertEqual(grok_events[0]["provider"], "grok-subscription")
        # no secret fields
        blob = json.dumps(events)
        self.assertNotIn("oauth", blob.lower())

    def test_git_guard_allows_commit_but_denies_publish_and_merge(self) -> None:
        from aipc_agent.router import subscription as sub

        env, guard = sub._guarded_env({"PATH": os.environ.get("PATH", "")})
        try:
            git = str(Path(env["PATH"].split(":", 1)[0]) / "git")
            version = __import__("subprocess").run(
                [git, "--version"], capture_output=True, text=True, check=False
            )
            self.assertEqual(version.returncode, 0)
            for command in ("push", "pull", "merge", "rebase"):
                denied = __import__("subprocess").run(
                    [git, command], capture_output=True, text=True, check=False
                )
                self.assertEqual(denied.returncode, 126, command)
        finally:
            guard.cleanup()

    def test_automation_snapshot_redacts_process_and_prompt(self) -> None:
        from aipc_agent.router import subscription as sub

        with sub._ACTIVE_LOCK:
            sub._ACTIVE["test-task"] = {
                "proc": object(),
                "task_id": "test-task",
                "provider": "codex-subscription",
                "repo": "/tmp/repo",
                "branch": "task/demo",
                "pid": 123,
                "state": "running",
                "started": 1.0,
                "last_activity": "working",
                "prompt": "secret prompt",
            }
        try:
            row = sub.automation_snapshot(include_finished=False)[0]
            self.assertNotIn("proc", row)
            self.assertNotIn("prompt", row)
            self.assertEqual(row["branch"], "task/demo")
        finally:
            with sub._ACTIVE_LOCK:
                sub._ACTIVE.pop("test-task", None)

    def test_ask_once_message(self) -> None:
        from aipc_agent.router import subscription as sub

        msg = sub.ask_once_message("codex-subscription", ["prompt"])
        self.assertIn("确认一次", msg)
        self.assertIn("codex", msg.lower())

    def test_confirmation_is_per_task_and_preserves_repo_scope(self) -> None:
        from aipc_agent.router import subscription as sub

        os.environ["AIPC_SUBSCRIPTION_GRANT_TEST"] = "1"
        try:
            msg = sub.request_confirmation(
                "confirm-session", "grok-subscription", "fix it", "/tmp"
            )
            self.assertIn("repo:/tmp", msg)
            approved = sub.consume_confirmation("confirm-session", "同意")
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(approved["provider"], "grok-subscription")
            self.assertIsNone(sub.consume_confirmation("confirm-session", "同意"))
        finally:
            os.environ.pop("AIPC_SUBSCRIPTION_GRANT_TEST", None)

    def test_resume_and_cancel_apis(self) -> None:
        from aipc_agent.router import subscription as sub

        ev = list(sub.resume("sess-1", "continue", dry_run=True))
        self.assertEqual(ev[0]["type"], "accepted")
        self.assertEqual(ev[-1]["type"], "result")
        # cancel unknown → structured error (not exception)
        out = sub.cancel("no-such-task")
        self.assertEqual(out["type"], "error")
        # cancel after dry accepted is fine (no proc)
        out2 = sub.cancel("dry-codex")
        self.assertIn(out2["type"], ("error", "result"))

    def test_paid_enabled_flip_allows_subscription_target(self) -> None:
        td = tempfile.TemporaryDirectory()
        try:
            pol_path = Path(td.name) / "routing-policy.yaml"
            pol_path.write_text(
                "policy_version: air-1\n"
                "slice: B\n"
                "authoritative: true\n"
                "paid_enabled: true\n"
                "auto_subscription: false\n"
                "metered_enabled: false\n"
                "shadow: true\n"
                "trace: false\n"
                "default_data_scopes: [prompt]\n",
                encoding="utf-8",
            )
            os.environ["AIPC_AGENT_ROUTING_POLICY"] = str(pol_path)
            import aipc_agent.router.policy as pol
            import aipc_agent.router.shadow as sh
            import aipc_agent.router.decide as dec

            importlib.reload(pol)
            importlib.reload(sh)
            importlib.reload(dec)
            d = sh.plan_shadow("用 Claude 写个排序", session_id="s", source="api")
            self.assertTrue(d["paid_allowed"], d)
            self.assertEqual(d["shadow_target"], "subscription")
            p = dec.plan_authoritative("用 Claude 写个排序", session_id="s", source="api")
            self.assertEqual(p["target"], "subscription")
            self.assertTrue(p["paid_allowed"])
        finally:
            os.environ.pop("AIPC_AGENT_ROUTING_POLICY", None)
            td.cleanup()
            import aipc_agent.router.policy as pol
            import aipc_agent.router.shadow as sh
            import aipc_agent.router.decide as dec

            importlib.reload(pol)
            importlib.reload(sh)
            importlib.reload(dec)


class TestQualityGateLive(unittest.TestCase):
    def test_ungrounded_live_without_trail(self) -> None:
        """Criterion 3: live/search turns fail gate even with empty trail."""
        from aipc_agent.router.analyze import analyze
        from aipc_agent.router.envelope import build_envelope
        from aipc_agent.router.quality import structural_gate

        a = analyze(build_envelope("今天台风动态", source="api"))
        self.assertIn(a["freshness"], ("live", "recent"))
        g = structural_gate(
            reply="今天台风很强，别出门。",
            required=list(a["required"]),
            freshness=a["freshness"],
            trail="",
        )
        self.assertIn("ungrounded_live", g["reasons"])
        self.assertFalse(g["ok"])


class TestHealthAndStats(unittest.TestCase):
    def test_health_snapshot_and_stats(self) -> None:
        from aipc_agent.router.health import snapshot
        from aipc_agent.router.stats import summarize_traces

        policy = (
            Path(__file__).resolve().parents[1]
            / "files"
            / "etc"
            / "aipc"
            / "agent"
            / "routing-policy.yaml"
        )
        os.environ["AIPC_AGENT_ROUTING_POLICY"] = str(policy)
        try:
            snap = snapshot()
            self.assertIn("litellm", snap)
            s = summarize_traces(limit=50)
            self.assertIn("samples", s)
            self.assertTrue(s.get("paid_enabled"))
            self.assertTrue(s.get("redaction_ok"))
        finally:
            os.environ.pop("AIPC_AGENT_ROUTING_POLICY", None)


class TestFeedbackAntiCase(unittest.TestCase):
    def test_negative_feedback_detected(self) -> None:
        from aipc_agent import feedback as fb

        self.assertTrue(fb.is_negative_feedback("不对"))
        self.assertTrue(fb.is_negative_feedback("乱答"))

    def test_feedback_plan_force_text_voice_tts_owner(self) -> None:
        """不对 → feedback path; voice client owns TTS (no dual agent speak)."""
        from aipc_agent.router.tts_owner import speak_owner_for
        from aipc_agent import feedback as fb

        self.assertTrue(fb.is_negative_feedback("不对"))
        # TTS ownership must stay with voice client for this session (no dual speak)
        self.assertEqual(speak_owner_for("voice", "voice-assistant"), "voice_client")
        self.assertNotEqual(speak_owner_for("voice", "voice-assistant"), "agent")
        # Drive plan_dispatch when langchain is available (agent venv / live)
        try:
            from aipc_agent.graphs import plan_dispatch

            p = plan_dispatch("不对", "voice-assistant", source="voice")
            self.assertEqual(p.get("reason"), "user-feedback-negative")
            self.assertTrue(p.get("force_text"))
        except ModuleNotFoundError:
            # Still proved feedback detection + TTS owner without dual agent speak
            pass


class TestAggregatorCapabilityFirst(unittest.TestCase):
    def test_needs_agent(self) -> None:
        # path: modules/agent-orchestrator/tests -> modules
        mod_root = Path(__file__).resolve().parents[2] / "assistant-aggregator" / "files" / "usr" / "lib"
        sys.path.insert(0, str(mod_root))
        from aipc_assistant.backends.local import _needs_agent_capabilities

        self.assertTrue(_needs_agent_capabilities("查一下用量"))
        self.assertTrue(_needs_agent_capabilities("今天台风"))
        self.assertFalse(_needs_agent_capabilities("你好"))


class TestHermesExecutionPolicy(unittest.TestCase):
    def test_bridge_bypasses_local_command_prompts(self) -> None:
        bridge = _ROOT / "aipc_agent" / "hermes_bridge.py"
        self.assertIn('"--yolo"', bridge.read_text(encoding="utf-8"))


class TestTechnicalAdvisor(unittest.TestCase):
    def test_packet_keeps_technical_artifacts_not_original_scenario(self) -> None:
        from aipc_agent.technical_advisor import build_packet

        packet = build_packet(
            "The private scenario must not reach the advisor.\n"
            "```python\nraise ValueError('bad state')\n```\n"
            "Traceback: ValueError: bad state\n"
            "token=sk-abcdefghijklmnopqrstuvwxyz"
        )
        self.assertNotIn("private scenario", packet)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", packet)
        self.assertIn("ValueError", packet)
        self.assertIn("raise ValueError", packet)

    def test_refusal_does_not_retry(self) -> None:
        from aipc_agent import technical_advisor

        with mock.patch.object(
            technical_advisor, "_chat", return_value="cannot_assist"
        ) as chat:
            self.assertIsNone(technical_advisor.advise("debug this Error: boom"))
        chat.assert_called_once()


class TestReplaySuite(unittest.TestCase):
    """Offline replay anti-cases from OpenSpec task 9.2."""

    CASES = [
        ("查一下用量", "daily_assistant", "voice_client", "voice", "voice-assistant"),
        ("今天 AMD 股价怎么样", "hermes", "agent", "api", "default"),
        ("你好", "respond", "voice_client", "voice", "voice-assistant"),
        ("用 Claude 写个排序", "hermes", "agent", "api", "default"),  # paid off → local hermes
        ("用 Codex 改 bug", "hermes", "agent", "api", "default"),
    ]

    def test_replay_targets(self) -> None:
        from aipc_agent.router.decide import plan_authoritative
        from aipc_agent.router.tts_owner import speak_owner_for

        for text, want_tgt, want_tts, source, sid in self.CASES:
            with self.subTest(text=text):
                p = plan_authoritative(text, session_id=sid, source=source)
                self.assertEqual(
                    p["target"],
                    want_tgt,
                    f"{text!r} → {p['target']} want {want_tgt} reasons={p.get('reason')}",
                )
                self.assertEqual(speak_owner_for(source, sid), want_tts)
                # Explicit providers recorded on decision
                if "Claude" in text or "Codex" in text:
                    from aipc_agent.router.analyze import analyze
                    from aipc_agent.router.envelope import build_envelope

                    a = analyze(build_envelope(text, session_id=sid, source=source))
                    self.assertTrue(a.get("explicit_provider"))

    def test_stt_garbage_then_followup_same_session(self) -> None:
        """STT garbage then a real follow-up under the same session_id."""
        from aipc_agent.router.decide import plan_authoritative

        sid = "voice-assistant-stt-test"
        g1 = plan_authoritative("嗯…那个…呃", session_id=sid, source="voice")
        # garbage should not escalate to subscription/paid
        self.assertFalse(g1.get("paid_allowed"))
        self.assertIn(g1["target"], ("respond", "clarify", "hermes", "daily_assistant"))
        g2 = plan_authoritative("查一下用量", session_id=sid, source="voice")
        self.assertEqual(g2["target"], "daily_assistant")
        self.assertEqual(g2.get("required"), ["usage_tools"])


if __name__ == "__main__":
    unittest.main()
