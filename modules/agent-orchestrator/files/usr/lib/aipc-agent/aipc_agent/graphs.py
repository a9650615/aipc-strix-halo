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
# main-70b (the spec's original default) was cut from models.yaml/llm-litellm
# 2026-07-04 in a manifest trim — ornith-35b (35B MoE reasoning + agentic
# coding) is the closest remaining fit for a supervisor role.
SUPERVISOR_MODEL = "ornith-35b"


class SupervisorState(TypedDict):
    text: str
    session_id: str


def _chat_model(model: str) -> ChatLiteLLM:
    return ChatLiteLLM(
        model=model,
        api_base=LITELLM_BASE_URL,
        custom_llm_provider="openai",
        api_key="aipc-local",
        # ornith-35b is a reasoning model with no natural stop point for
        # hidden thinking tokens — hardware-verified 2026-07-05: an
        # unbounded call took minutes past a plain "reply with exactly:
        # pong" before this cap was added. 2048 covers reasoning + a real
        # answer without letting one request run indefinitely.
        max_tokens=2048,
    )


def _text_of(content: str | list) -> str:
    """Reasoning models (ornith-35b) return content as a list of blocks
    (thinking + text), not a plain string — hardware-verified 2026-07-04.
    Take the final "text"-type block; fall back to str() for anything else."""
    if isinstance(content, str):
        return content
    for block in reversed(content):
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return str(content)


def _respond(state: SupervisorState) -> SupervisorState:
    reply = _chat_model(SUPERVISOR_MODEL).invoke(state["text"])
    return {"text": _text_of(reply.content), "session_id": state["session_id"]}


def supervisor():
    graph = StateGraph(SupervisorState)
    graph.add_node("respond", _respond)
    graph.set_entry_point("respond")
    graph.add_edge("respond", END)
    return graph.compile()
