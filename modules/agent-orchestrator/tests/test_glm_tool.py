from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "files/usr/lib/aipc-agent"
sys.path.insert(0, str(ROOT))


def test_unknown_quota_keeps_request_local() -> None:
    from aipc_agent.glm_tool import ask_glm

    called = False

    def post(_: str) -> str:
        nonlocal called
        called = True
        return "unexpected"

    result = ask_glm("compare two APIs", lookup=lambda _: {"status": "error"}, post=post)

    assert result["status"] == "local_only"
    assert called is False


def test_available_quota_calls_glm_once() -> None:
    from aipc_agent.glm_tool import ask_glm

    prompts: list[str] = []

    result = ask_glm(
        "compare two APIs",
        lookup=lambda _: {
            "status": "ok",
            "providers": [{"id": "zai", "remaining_percent": 80}],
        },
        post=lambda prompt: prompts.append(prompt) or "answer",
    )

    assert result == {"status": "ok", "tool": "ask_glm", "content": "answer"}
    assert prompts == ["compare two APIs"]


def test_explicit_secret_assignment_stays_local() -> None:
    from aipc_agent.glm_tool import ask_glm

    called = False

    def post(_: str) -> str:
        nonlocal called
        called = True
        return "unexpected"

    result = ask_glm(
        "debug api_key=1234567890abcdef",
        lookup=lambda _: {
            "status": "ok",
            "providers": [{"id": "zai", "remaining_percent": 80}],
        },
        post=post,
    )

    assert result["status"] == "local_only"
    assert called is False


def test_daily_assistant_binds_ask_glm_but_not_direct_fast_path() -> None:
    source = (ROOT / "aipc_agent/daily_assistant.py").read_text()

    assert "def ask_glm(prompt: str)" in source
    assert "    ask_glm," in source
    assert "ask_glm (optional cloud second opinion" in source
    direct = source[source.index("def try_direct_tool"):]
    assert '"ask_glm"' not in direct
