"""LangGraph graphs for the agent-orchestrator daemon.

Basic-skeleton scope (openspec/changes/phase-4-agent tasks 2.1/2.2):
`supervisor` answers directly for most text, and routes to the Daily
Assistant sub-graph (task 2.6, `daily_assistant.py`) on an explicit keyword
match. This is a simple explicit route, not the generic multi-agent router
the full spec eventually wants — that waits until Researcher/Coder/Browser
(tasks 2.3-2.5) exist too and a real decomposition step is worth building.

Every model call goes through the LiteLLM gateway (CLAUDE.md §7) — never a
direct backend URL (Ollama, Lemonade, vLLM, or any cloud provider).

Always-on voice closed loop (2026-07-10): default supervisor is
resident-small (NPU) so SenseVoice → /chat → Kokoro stays fast and does not
depend on Vulkan agent models (ornith / coder-agentic). Override with
AIPC_SUPERVISOR_MODEL when the user has switched into agent role.
"""

import os
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, StateGraph

from aipc_agent import memory
from aipc_agent._util import text_of
from aipc_agent.daily_assistant import daily_assistant

LITELLM_BASE_URL = "http://127.0.0.1:4000"
# Closed-loop default: always-on NPU small model. Heavy agent LLMs are
# optional via env (or future aipc models use agent wiring).
SUPERVISOR_MODEL = os.environ.get("AIPC_SUPERVISOR_MODEL", "resident-small")

# Without a system prompt the model has no idea it's "the aipc assistant"
# and answers like a disconnected generic chatbot (e.g. "I'm an AI, I can't
# open apps for you" instead of something aware of its own actual, still-
# growing toolset) — a real user complaint, not hypothetical. Keep this in
# sync with daily_assistant.SYSTEM_PROMPT's capability list as tools land.
SUPERVISOR_SYSTEM_PROMPT = (
    "You are the aipc assistant on this user's AMD Strix Halo AI PC. "
    "Inference is local (no cloud). Answer briefly and in the user's language. "
    "Local memory (mem0) may inject remembered facts — use them when present. "
    "Always-on stack: resident-small (you), SenseVoice STT, Kokoro TTS, mem0. "
    "The user can open the AIPC management portal by voice (local intent, not you): "
    "phrases like 'open dashboard' / '打开面板'. "
    "You cannot control the screen or browse the web yourself — say so plainly if asked."
)

# ponytail: keyword match, not intent classification — good enough to reach
# the Daily Assistant sub-graph today; replace with real routing once a
# second sub-agent (2.3-2.5) makes a keyword list unworkable.
# Keep "remember/memory" off this list so mem0 stays on the fast supervisor.
_DAILY_ASSISTANT_KEYWORDS = (
    "calendar", "schedule", "meeting", "email", "inbox", "mail",
    "file", "read",
    # usage / quota questions → Daily Assistant (has usage_lookup tool)
    "usage", "quota", "token", "tokens", "rate limit", "codex", "claude",
    "用量", "額度", "配額",
)


class SupervisorState(TypedDict):
    text: str
    session_id: str


def _chat_model(model: str) -> ChatLiteLLM:
    # resident-small is short-form voice; heavy reasoning models need more.
    max_tokens = 512 if model == "resident-small" else 2048
    return ChatLiteLLM(
        model=model,
        api_base=LITELLM_BASE_URL,
        custom_llm_provider="openai",
        api_key="aipc-local",
        max_tokens=max_tokens,
    )


def _memory_messages(state: SupervisorState) -> list[SystemMessage]:
    remembered = memory.recall(state["text"], state["session_id"])
    if not remembered:
        return []
    return [SystemMessage(content=f"Relevant remembered facts:\n{remembered}")]


def _respond(state: SupervisorState) -> SupervisorState:
    messages = [SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT), *_memory_messages(state), HumanMessage(content=state["text"])]
    reply = _chat_model(SUPERVISOR_MODEL).invoke(messages)
    text = text_of(reply.content)
    memory.remember(f"User: {state['text']}\nAssistant: {text}", state["session_id"])
    return {"text": text, "session_id": state["session_id"]}


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
    denied = da.files_read.invoke({"path": "/etc/passwd"})
    assert denied["status"] in {"not_configured", "denied"}
    assert "root:" not in str(denied)
    usage = da.usage_lookup.invoke({"providers": ""})
    assert usage["tool"] == "usage.lookup"
    assert usage["status"] in {"ok", "error", "not_configured"}
    assert isinstance(usage.get("providers"), list)
    assert _route({"text": "how much claude quota do I have left", "session_id": "s"}) == "daily_assistant"

    captured = {}
    real_init = ChatLiteLLM.__init__

    def fake_init(self, *args, **kwargs):
        captured["model"] = kwargs.get("model")
        real_init(self, *args, **kwargs)

    with patch.object(ChatLiteLLM, "__init__", fake_init):
        da._chat_model()
    assert captured["model"] == da.DAILY_ASSISTANT_MODEL == "ornith-35b"

    with patch.object(memory, "recall", return_value="likes concise replies") as recall, \
         patch.object(memory, "remember") as remember, \
         patch.object(ChatLiteLLM, "invoke", return_value=AIMessage(content="mocked reply")):
        assert graph.invoke({"text": "hello", "session_id": "s1"})["text"] == "mocked reply"
        result = da_graph.invoke({"text": "book a meeting", "session_id": "s2", "messages": []})
        assert result["text"] == "mocked reply"
        assert recall.call_count == 2
        assert remember.call_count == 2

    print("self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
