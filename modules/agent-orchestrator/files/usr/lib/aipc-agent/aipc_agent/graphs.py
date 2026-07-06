"""LangGraph graphs for the agent-orchestrator daemon.

Basic-skeleton scope (openspec/changes/phase-4-agent tasks 2.1/2.2):
`supervisor` answers directly for most text, and routes to the Daily
Assistant sub-graph (task 2.6, `daily_assistant.py`) on an explicit keyword
match. This is a simple explicit route, not the generic multi-agent router
the full spec eventually wants — that waits until Researcher/Coder/Browser
(tasks 2.3-2.5) exist too and a real decomposition step is worth building.

Every model call goes through the LiteLLM gateway (CLAUDE.md §7) — never a
direct backend URL (Ollama, Lemonade, vLLM, or any cloud provider).
"""

from typing import TypedDict

from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, StateGraph

from aipc_agent.daily_assistant import daily_assistant

LITELLM_BASE_URL = "http://127.0.0.1:4000"
# main-70b (the spec's original default) was cut from models.yaml/llm-litellm
# 2026-07-04 in a manifest trim — ornith-35b (35B MoE reasoning + agentic
# coding) is the closest remaining fit for a supervisor role.
SUPERVISOR_MODEL = "ornith-35b"

# ponytail: keyword match, not intent classification — good enough to reach
# the Daily Assistant sub-graph today; replace with real routing once a
# second sub-agent (2.3-2.5) makes a keyword list unworkable.
_DAILY_ASSISTANT_KEYWORDS = ("calendar", "schedule", "meeting", "email", "inbox", "mail")


class SupervisorState(TypedDict):
    text: str
    session_id: str


def _chat_model(model: str) -> ChatLiteLLM:
    return ChatLiteLLM(
        model=model,
        api_base=LITELLM_BASE_URL,
        custom_llm_provider="openai",
        api_key="aipc-local",
    )


def _respond(state: SupervisorState) -> SupervisorState:
    reply = _chat_model(SUPERVISOR_MODEL).invoke(state["text"])
    return {"text": reply.content, "session_id": state["session_id"]}


_daily_assistant_graph = daily_assistant()


def _daily_assistant_node(state: SupervisorState) -> SupervisorState:
    result = _daily_assistant_graph.invoke(
        {"text": state["text"], "session_id": state["session_id"], "messages": []}
    )
    return {"text": result["text"], "session_id": state["session_id"]}


def _route(state: SupervisorState) -> str:
    text = state["text"].lower()
    if any(kw in text for kw in _DAILY_ASSISTANT_KEYWORDS):
        return "daily_assistant"
    return "respond"


def supervisor():
    graph = StateGraph(SupervisorState)
    graph.add_node("respond", _respond)
    graph.add_node("daily_assistant", _daily_assistant_node)
    graph.set_conditional_entry_point(_route, {"respond": "respond", "daily_assistant": "daily_assistant"})
    graph.add_edge("respond", END)
    graph.add_edge("daily_assistant", END)
    return graph.compile()


def self_test() -> None:
    """Assert-based self-check, no network: construct-only + mocked LLM.

    Run: `venv/bin/python3 -m aipc_agent.graphs --self-test`
    """
    from unittest.mock import patch

    from langchain_core.messages import AIMessage

    from aipc_agent import daily_assistant as da

    graph = supervisor()
    da_graph = da.daily_assistant()

    assert _route({"text": "what's on my calendar today", "session_id": "s"}) == "daily_assistant"
    assert _route({"text": "what is the capital of France", "session_id": "s"}) == "respond"

    assert da.calendar_lookup.invoke({"query": "x"})["status"] == "not_configured"
    assert da.email_lookup.invoke({"query": "x"})["status"] == "not_configured"
    assert da.files_read.invoke({"path": "/etc/passwd"})["status"] == "not_configured"

    captured = {}
    real_init = ChatLiteLLM.__init__

    def fake_init(self, *args, **kwargs):
        captured["model"] = kwargs.get("model")
        real_init(self, *args, **kwargs)

    with patch.object(ChatLiteLLM, "__init__", fake_init):
        da._chat_model()
    assert captured["model"] == da.DAILY_ASSISTANT_MODEL == "intent-3b"

    with patch.object(ChatLiteLLM, "invoke", return_value=AIMessage(content="mocked reply")):
        assert graph.invoke({"text": "hello", "session_id": "s1"})["text"] == "mocked reply"
        result = da_graph.invoke({"text": "book a meeting", "session_id": "s2", "messages": []})
        assert result["text"] == "mocked reply"

    print("self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
