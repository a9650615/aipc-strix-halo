from __future__ import annotations

import sys
from importlib import import_module
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "files/usr/lib/aipc-agent"
sys.path.insert(0, str(ROOT))

glm_tool = import_module("aipc_agent.glm_tool")
ask_glm = glm_tool.ask_glm
next_data_scopes = glm_tool.next_data_scopes


def test_unknown_quota_keeps_request_local() -> None:
    called = False

    def post(_: str) -> str:
        nonlocal called
        called = True
        return "unexpected"

    result = ask_glm(
        "compare two APIs",
        data_scope="prompt",
        interaction="foreground",
        lookup=lambda _: {"status": "error"},
        post=post,
    )

    assert result["status"] == "local_only"
    assert called is False


def test_available_quota_calls_glm_once() -> None:
    from aipc_agent.glm_tool import ask_glm

    prompts: list[str] = []

    result = ask_glm(
        "compare two APIs",
        lookup=lambda _: {
            "status": "ok",
            "providers": [{
                "id": "zai",
                "remaining_percent": 80,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        },
        data_scope="prompt",
        interaction="foreground",
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
            "providers": [{
                "id": "zai",
                "remaining_percent": 80,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        },
        data_scope="prompt",
        interaction="foreground",
        post=post,
    )

    assert result["status"] == "local_only"
    assert called is False


def test_stale_quota_keeps_request_local() -> None:
    from aipc_agent.glm_tool import ask_glm

    result = ask_glm(
        "compare two APIs",
        data_scope="prompt",
        interaction="foreground",
        lookup=lambda _: {
            "status": "ok",
            "providers": [{
                "id": "zai",
                "remaining_percent": 80,
                "updated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            }],
        },
        post=lambda _: "unexpected",
    )
    assert result["status"] == "local_only"


def test_private_scope_or_background_keeps_request_local() -> None:
    from aipc_agent.glm_tool import ask_glm

    def fresh(_: str) -> dict:
        return {
            "status": "ok",
            "providers": [{
                "id": "zai",
                "remaining_percent": 80,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }],
        }
    assert ask_glm(
        "summarize this",
        data_scope="email",
        interaction="foreground",
        lookup=fresh,
        post=lambda _: "unexpected",
    )["status"] == "local_only"
    assert ask_glm(
        "compare two APIs",
        data_scope="prompt",
        interaction="background",
        lookup=fresh,
        post=lambda _: "unexpected",
    )["status"] == "local_only"


def test_daily_assistant_binds_ask_glm_but_not_direct_fast_path() -> None:
    source = (ROOT / "aipc_agent/daily_assistant.py").read_text()

    assert "def ask_glm(prompt: str, state: Annotated[dict, InjectedState])" in source
    assert 'data_scope = "prompt" if state.get("data_scopes") == ["prompt"] else "private"' in source
    assert 'interaction=str(state.get("interaction") or "background")' in source
    assert "    ask_glm," in source
    assert "ask_glm (optional cloud second opinion" in source
    direct = source[source.index("def try_direct_tool"):]
    assert '"ask_glm"' not in direct


def test_supervisor_injects_trusted_glm_execution_scope() -> None:
    source = (ROOT / "aipc_agent/graphs.py").read_text()

    assert '"data_scopes": ["prompt"]' in source
    assert '"interaction": interaction' in source


def test_private_tool_result_taints_later_glm_call() -> None:
    scopes = next_data_scopes(["prompt"], ["calendar"])
    scopes = next_data_scopes(scopes, ["ask_glm"])

    assert scopes == ["private"]
