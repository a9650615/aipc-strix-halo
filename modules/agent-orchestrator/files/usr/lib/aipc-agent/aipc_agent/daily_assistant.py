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

Tool backend state:
- calendar / email: agent-tools-calendar (tasks 4.2-4.4) landed as a sibling
  module (modules/agent-tools-calendar/) exposing lookup_events/lookup_email.
  Falls back to "not_configured" if the import fails (module not rendered).
- search: agent-tools-search (tasks 4.5-4.6) landed as a sibling module
  exposing search_searxng/search_tavily; Tavily only lights up once a real
  key resolves at runtime (see that module's README for the outstanding
  decrypt-cloud-keys.sh gap).
- files.read: agent-tools-files (task 4.1) landed as a sibling module
  (modules/agent-tools-files/). post-install exposes /usr/lib/aipc-agent to
  this venv so the import works when both modules are rendered. Assumed
  interface (matches the real module, confirmed by inspection):

      from aipc_agent_tools_files import read_file
      def read_file(path: str) -> str: ...  # raises PermissionError if
                                              # `path` is outside the
                                              # allowlist

  Falls back to the same "not_configured" stub if the import fails.
- memory: optional mem0 HTTP client; missing/unreachable memory fails soft.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from aipc_agent import memory
from aipc_agent._util import text_of

LITELLM_BASE_URL = "http://127.0.0.1:4000"
DAILY_ASSISTANT_MODEL = "ornith-35b"

# Keep this list in sync with TOOLS above and graphs.SUPERVISOR_SYSTEM_PROMPT
# as real backends land — a user hit this directly: without a system prompt
# the model apologized like a disconnected generic chatbot instead of using
# its own tools and reporting their real (not_configured) status.
SYSTEM_PROMPT = (
    "You are the aipc assistant's Daily Assistant persona, running locally "
    "on the user's own AI PC. You have tools for calendar, email, and file "
    "access, plus best-effort local memory when mem0 is available, but most "
    "tool backends are still incomplete — when a tool "
    "returns a not_configured status, tell the user plainly that this "
    "specific feature isn't set up yet, don't apologize generically. You "
    "cannot control the screen or launch applications."
)


@tool
def calendar_lookup(query: str) -> dict:
    """Look up calendar events matching `query`."""
    try:
        from aipc_agent_tools_calendar import lookup_events  # phase-4-agent#4.2-4.4
    except ImportError:
        return {
            "status": "not_configured",
            "tool": "calendar",
            "detail": "agent-tools-calendar not installed yet (phase-4-agent#4.2-4.4)",
        }
    return lookup_events(query)


@tool
def email_lookup(query: str) -> dict:
    """Search email matching `query`."""
    try:
        from aipc_agent_tools_calendar import lookup_email  # phase-4-agent#4.2-4.4
    except ImportError:
        return {
            "status": "not_configured",
            "tool": "email",
            "detail": "agent-tools-calendar not installed yet (phase-4-agent#4.2-4.4)",
        }
    return lookup_email(query)


@tool
def search(query: str, limit: int = 5) -> dict:
    """Search the web via self-hosted SearXNG, falling back to nothing if
    unreachable. Advertise search_tavily separately only when configured
    (aipc_agent_tools_search.available_tools() tells you which)."""
    try:
        from aipc_agent_tools_search import search_searxng  # phase-4-agent#4.5
    except ImportError:
        return {
            "status": "not_configured",
            "tool": "search",
            "detail": "agent-tools-search not installed yet (phase-4-agent#4.5)",
        }
    return search_searxng(query, limit=limit)


@tool
def search_tavily(query: str, limit: int = 5) -> dict:
    """Paid-tier web search via Tavily. Only useful when TAVILY_API_KEY is
    configured -- returns {"status": "not_configured"} otherwise, so check
    aipc_agent_tools_search.available_tools() before relying on this."""
    try:
        from aipc_agent_tools_search import search_tavily as _search_tavily  # phase-4-agent#4.6
    except ImportError:
        return {
            "status": "not_configured",
            "tool": "search_tavily",
            "detail": "agent-tools-search not installed yet (phase-4-agent#4.6)",
        }
    return _search_tavily(query, limit=limit)


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


TOOLS = [calendar_lookup, email_lookup, files_read, search, search_tavily]


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


def _memory_messages(state: DailyAssistantState) -> list[SystemMessage]:
    remembered = memory.recall(state["text"], state["session_id"])
    if not remembered:
        return []
    return [SystemMessage(content=f"Relevant remembered facts:\n{remembered}")]


def _seed(state: DailyAssistantState) -> dict:
    return {"messages": [SystemMessage(content=SYSTEM_PROMPT), *_memory_messages(state), HumanMessage(content=state["text"])]}


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
    text = text_of(state["messages"][-1].content)
    memory.remember(f"User: {state['text']}\nAssistant: {text}", state["session_id"])
    return {"text": text, "session_id": state["session_id"]}


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
