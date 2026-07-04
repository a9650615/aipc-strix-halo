"""LangGraph graphs for the agent-orchestrator daemon.

Basic-skeleton scope (openspec/changes/phase-4-agent tasks 2.1/2.2): only
`supervisor` exists — a single-node graph that answers directly. It does
NOT yet dispatch to sub-agents (Researcher/Coder/Browser/Daily Assistant);
that's tasks 2.3-2.6, deferred.

Every model call goes through the LiteLLM gateway (CLAUDE.md §7) — never a
direct backend URL (Ollama, Lemonade, vLLM, or any cloud provider).
"""

from typing import TypedDict

from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, StateGraph

LITELLM_BASE_URL = "http://127.0.0.1:4000"
SUPERVISOR_MODEL = "main-70b"


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


def supervisor():
    graph = StateGraph(SupervisorState)
    graph.add_node("respond", _respond)
    graph.set_entry_point("respond")
    graph.add_edge("respond", END)
    return graph.compile()
