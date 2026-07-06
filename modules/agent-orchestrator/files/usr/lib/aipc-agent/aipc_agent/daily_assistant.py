"""LangGraph graph for the Daily Assistant sub-agent.

openspec/changes/phase-4-agent task 2.6: the spec's default model
`intent-3b` doesn't exist — it was part of the qwen2.5 family cut wholesale
in the 2026-07-04 models.yaml trim (see llm-models's models.yaml comment).
Tried `resident-small` next (the one small always-resident local model
left) but hardware-verified 2026-07-06 that it can't do tool calling at
all: `resident-small` runs on Lemonade's FastFlowLM NPU backend (response
`id: fastflowlm-chat-completion`), and any `/chat/completions` call that
includes a `tools` list 500s there with `[json.exception.type_error.302]
type must be string, but is object` — a real NPU-backend limitation, not a
request-shape bug (confirmed: the identical tools payload against
`ornith-35b`, Lemonade's Vulkan/llama.cpp backend, returns a proper
`tool_calls` response). Since Daily Assistant needs tool calling to be
useful at all, it reuses `ornith-35b` — the supervisor's own model,
already verified for structured tool-calling — until a small
tool-calling-capable NPU model exists. Calls go via the LiteLLM gateway
(CLAUDE.md §7 — never a direct backend URL), with calendar/email/files-read
tools bound to it. Wired into `graphs.supervisor()` as an explicit keyword
routed dispatch target — not a generic multi-agent router (that's future
scope once Researcher/Coder/Browser exist too).

None of the three tool backends exist yet:
- calendar / email: agent-tools-calendar (tasks 4.2-4.4) is unimplemented.
  Stubbed to fail closed with a structured "not_configured" response.
- files.read: agent-tools-files (task 4.1) landed as a sibling module
  (modules/agent-tools-files/) but isn't installed into this venv yet —
  the import below still fails until it's wired into agent-orchestrator's
  requirements/post-install. Assumed interface (matches the real module,
  confirmed by inspection):

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

from aipc_agent._util import text_of

LITELLM_BASE_URL = "http://127.0.0.1:4000"
DAILY_ASSISTANT_MODEL = "ornith-35b"


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
    # ornith-35b (a reasoning model) returns content as a block list
    # (e.g. {"type": "thinking", ...}); llama-server rejects that shape if
    # this message is ever re-sent as history on the next tool-loop turn
    # ("unsupported content[].type" — hardware-verified 2026-07-06).
    # Normalize before it lands in state; tool_calls are untouched.
    reply.content = text_of(reply.content)
    return {"messages": [reply]}


def _finish(state: DailyAssistantState) -> dict:
    return {"text": text_of(state["messages"][-1].content), "session_id": state["session_id"]}


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
