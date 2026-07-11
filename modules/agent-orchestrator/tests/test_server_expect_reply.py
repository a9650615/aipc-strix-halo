"""expect_reply plumbing: /chat HTTP response surfaces clarify_question.

turn-state-contract (phase-3-voice-assistant): voice clients need a signal
that the assistant is asking the user something, distinct from end_session.
We reuse the graph's existing `clarify_question` field rather than a new
classifier — this test locks that `expect_reply_from_result` derives from it.

Skips cleanly if fastapi isn't installed (server.py's only non-stdlib import
needed for this pure helper); see test_overlay_markdown.py for the same
importorskip convention used elsewhere in this repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "aipc-agent"
sys.path.insert(0, str(_ROOT))


def _server():
    pytest.importorskip("fastapi")
    pytest.importorskip("pydantic")
    try:
        from aipc_agent import server
    except ImportError as exc:  # e.g. langchain_core missing transitively
        pytest.skip(f"aipc_agent.server import chain incomplete: {exc}")
    return server


def test_expect_reply_true_when_clarify_question_set():
    server = _server()
    assert server.expect_reply_from_result({"clarify_question": "哪支股票？"}) is True


def test_expect_reply_false_when_clarify_question_blank():
    server = _server()
    assert server.expect_reply_from_result({"clarify_question": ""}) is False
    assert server.expect_reply_from_result({}) is False


def test_expect_reply_false_for_non_dict_result():
    server = _server()
    assert server.expect_reply_from_result(None) is False
    assert server.expect_reply_from_result("not a dict") is False
