"""LangGraph graph for the Daily Assistant sub-agent.

openspec/changes/phase-4-agent task 2.6: `intent-3b` via the LiteLLM gateway
(CLAUDE.md §7 — never a direct backend URL), with calendar/email/files-read
tools bound to it. Wired into `graphs.supervisor()` as an explicit keyword
routed dispatch target — not a generic multi-agent router (that's future
scope once Researcher/Coder/Browser exist too).

None of the three tool backends exist yet:
- calendar / email: agent-tools-calendar (tasks 4.2-4.4) is unimplemented.
  Stubbed to fail closed with a structured "not_configured" response.
- files.read: agent-tools-files (task 4.1) is being built in parallel in a
  sibling module (modules/agent-tools-files/), not present in this working
  tree. Assumed interface (see README for the full contract so the two wire
  together later):

      from aipc_agent_tools_files import read_file
      def read_file(path: str) -> str: ...  # raises PermissionError if
                                              # `path` is outside the
                                              # allowlist

  Falls back to the same "not_configured" stub if the import fails.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

LITELLM_BASE_URL = "http://127.0.0.1:4000"
DAILY_ASSISTANT_MODEL = "intent-3b"


@tool
def calendar_lookup(query: str) -> dict:
    """Look up calendar events matching `query`."""
    # ponytail: stub — agent-tools-calendar (phase-4-agent#4.2/4.3/4.4:
    # Google/Proton/Fastmail backends) doesn't exist yet. Replace this body
    # once one of those lands.
    return {
        "status": "not_configured",
        "tool": "calendar",
        "detail": "no calendar backend configured yet (phase-4-agent#4.2-4.4)",
    }


@tool
def email_lookup(query: str) -> dict:
    """Search email matching `query`."""
    # ponytail: stub — same as calendar_lookup, no email backend yet.
    return {
        "status": "not_configured",
        "tool": "email",
        "detail": "no email backend configured yet (phase-4-agent#4.2-4.4)",
    }


@tool
def files_read(path: str) -> dict:
    """Read a file from the agent workspace at `path`."""
    try:
        from aipc_agent_tools_files import read_file  # phase-4-agent#4.1
    except ImportError:
        # ponytail: agent-tools-files (phase-4-agent#4.1) isn't installed
        # yet — fail closed instead of touching the filesystem directly.
        return {
            "status": "not_configured",
            "tool": "files.read",
            "detail": "agent-tools-files not installed yet (phase-4-agent#4.1)",
        }
    try:
        return {"status": "ok", "tool": "files.read", "content": read_file(path)}
    except PermissionError as exc:
        return {"status": "denied", "tool": "files.read", "detail": str(exc)}


TOOLS = [calendar_lookup, email_lookup, files_read]


class DailyAssistantState(TypedDict):
    text: str
    session_id: str
    messages: Annotated[list, add_messages]


def _chat_model() -> ChatLiteLLM:
    return ChatLiteLLM(
        model=DAILY_ASSISTANT_MODEL,
        api_base=LITELLM_BASE_URL,
        custom_llm_provider="openai",
        api_key="aipc-local",
    ).bind_tools(TOOLS)


def _seed(state: DailyAssistantState) -> dict:
    return {"messages": [HumanMessage(content=state["text"])]}


def _agent(state: DailyAssistantState) -> dict:
    reply = _chat_model().invoke(state["messages"])
    return {"messages": [reply]}


def _finish(state: DailyAssistantState) -> dict:
    return {"text": state["messages"][-1].content, "session_id": state["session_id"]}


def daily_assistant():
    graph = StateGraph(DailyAssistantState)
    graph.add_node("seed", _seed)
    graph.add_node("agent", _agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_node("finish", _finish)
    graph.set_entry_point("seed")
    graph.add_edge("seed", "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: "finish"})
    graph.add_edge("tools", "agent")
    graph.add_edge("finish", END)
    return graph.compile()
