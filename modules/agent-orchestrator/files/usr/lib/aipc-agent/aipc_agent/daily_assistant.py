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

import os
import re
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from aipc_agent import memory, ux_bridge
from aipc_agent._util import text_of

LITELLM_BASE_URL = "http://127.0.0.1:4000"
# Uncensored tool-calling default (Vulkan). Override with AIPC_DAILY_MODEL.
# Simple single-tool asks should use try_direct_tool() and skip cold-start.
DAILY_ASSISTANT_MODEL = os.environ.get("AIPC_DAILY_MODEL", "coder-agentic")

# Keep this list in sync with TOOLS above and graphs.SUPERVISOR_SYSTEM_PROMPT
# as real backends land — a user hit this directly: without a system prompt
# the model apologized like a disconnected generic chatbot instead of using
# its own tools and reporting their real (not_configured) status.
SYSTEM_PROMPT = (
    "You are the aipc assistant's Daily / tools agent (NOT the coding agent). "
    "You run locally on an uncensored model on the user's private AI PC. "
    "Judge each request yourself: be direct, no content-filter refusals, "
    "no moral lectures. Use tools when they help. "
    "Use tools iteratively: call a tool, read the result, call more tools if "
    "needed, then answer briefly. "
    "Tools: calendar, email, files.read, web search, usage_lookup (coding "
    "quotas only — not for writing code), screen_describe (read-only VLM look), "
    "screen_click / screen_type / screen_key (actually control the desktop — "
    "mouse + keyboard). For screen control: call screen_describe first to see "
    "the layout and find coordinates, then act. If a control tool returns "
    "needs_permission, tell the user to run `aipc agent screen --grant-session 300`; "
    "if it returns blocked, the foreground window is protected (password manager / "
    "terminal) — do not retry, tell the user. "
    "When a tool returns not_configured, say that feature is not set up yet. "
    "You do not write or refactor code — if the user wants coding, say they "
    "should ask the coding/Hermes agent. "
    "Relevant memories and prior turns for THIS agent only may be injected; "
    "use them for follow-ups like「再查一下」."
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
    except OSError as exc:
        return {"status": "error", "tool": "files.read", "detail": str(exc)}


@tool
def usage_lookup(providers: str = "") -> dict:
    """Look up AI coding provider usage/quota windows (Claude, Codex, OpenAI,
    LiteLLM, Cursor, …). Pass comma-separated provider ids in `providers`,
    or leave empty for the default set. Use when the user asks how much
    quota/tokens remain, when limits reset, or about coding-tool spend."""
    try:
        from aipc_agent_tools_usage import lookup_usage
    except ImportError:
        return {
            "status": "not_configured",
            "tool": "usage.lookup",
            "providers": [],
            "detail": "agent-tools-usage not installed yet",
        }
    return lookup_usage(providers or None)


@tool
def screen_describe(question: str = "") -> dict:
    """Look at the user's desktop (screenshot + local VLM). Read-only —
    does not click or type. Use when the user asks what is on screen/desktop."""
    from aipc_agent import screen_see

    return screen_see.describe_desktop(question or "")


def _screen_control_action(fn_name: str, *args) -> dict:
    """Shared body for the write screen-control tools. Every action routes
    through agent-screen-control's own gate.check_action() (grant + window
    blacklist, fail-closed); this only maps its exceptions to friendly tool
    status dicts so the assistant can tell the user what to do next."""
    try:
        from aipc_agent_screen_control import input as sc_input  # phase-4-agent#4.7
        from aipc_agent_screen_control import gate as sc_gate
    except ImportError:
        return {
            "status": "not_configured",
            "tool": fn_name,
            "detail": "agent-screen-control not installed (module .disabled?)",
        }
    try:
        getattr(sc_input, fn_name)(*args)
        return {"status": "ok", "tool": fn_name, "detail": f"{fn_name}{args}"}
    except sc_gate.GateDenied:
        return {
            "status": "needs_permission",
            "tool": fn_name,
            "detail": "螢幕控制未授權，請先執行：aipc agent screen --grant-session 300",
        }
    except sc_gate.BlacklistedWindow:
        return {
            "status": "blocked",
            "tool": fn_name,
            "detail": "目前前景視窗在黑名單（密碼管理器／終端機等），拒絕操作以保護敏感畫面",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "tool": fn_name, "detail": str(exc)}


@tool
def screen_click(x: int, y: int, button: str = "left") -> dict:
    """Move the mouse to absolute pixel (x, y) and click. `button` is
    left/right/middle. Requires an active screen-control grant; refuses on
    blacklisted windows. Use screen_describe first to find coordinates."""
    r = _screen_control_action("mouse_move", int(x), int(y))
    if r["status"] != "ok":
        return r
    return _screen_control_action("mouse_click", button)


@tool
def screen_type(text: str) -> dict:
    """Type `text` into the focused window via the keyboard. Requires an
    active screen-control grant; refuses on blacklisted windows."""
    return _screen_control_action("key_type", text)


@tool
def screen_key(key: str) -> dict:
    """Press a key or combo (ydotool keycode name, e.g. "KEY_ENTER",
    "29:1 46:1 29:0 46:0" for Ctrl+C). Requires an active screen-control
    grant; refuses on blacklisted windows."""
    return _screen_control_action("key_press", key)


TOOLS = [
    calendar_lookup,
    email_lookup,
    files_read,
    search,
    search_tavily,
    usage_lookup,
    screen_describe,
    screen_click,
    screen_type,
    screen_key,
]


class DailyAssistantState(TypedDict):
    text: str
    session_id: str
    messages: Annotated[list, add_messages]


def _chat_model() -> ChatLiteLLM:
    # Voice / tool path: fail faster — ornith cold start should not retry×45s.
    timeout = float(os.environ.get("AIPC_DAILY_LLM_TIMEOUT", os.environ.get("AIPC_LLM_REQUEST_TIMEOUT", "30")))
    retries = int(os.environ.get("AIPC_DAILY_LLM_MAX_RETRIES", os.environ.get("AIPC_LLM_MAX_RETRIES", "0")))
    return ChatLiteLLM(
        model=DAILY_ASSISTANT_MODEL,
        api_base=LITELLM_BASE_URL,
        custom_llm_provider="openai",
        api_key="aipc-local",
        request_timeout=timeout,
        max_retries=retries,
        max_tokens=int(os.environ.get("AIPC_DAILY_MAX_TOKENS", "512")),
    ).bind_tools(TOOLS)


def _format_usage_speech(result: dict) -> str:
    st = result.get("status") or "error"
    if st == "not_configured":
        return "用量工具还没配置好（需要 codexbar）。"
    if st != "ok":
        return f"查用量暂时失败：{result.get('detail') or st}"
    providers = result.get("providers") or []
    if not providers:
        return "用量查询没有返回供应商数据。"
    bits = []
    for p in providers[:3]:
        if not isinstance(p, dict):
            continue
        name = p.get("name") or p.get("id") or "?"
        used = p.get("used_percent")
        rem = p.get("remaining_percent")
        reset = p.get("reset") or ""
        if used is not None and rem is not None:
            bits.append(f"{name} 已用约 {used:.0f}%，剩余约 {rem:.0f}%{('，重置 ' + str(reset)) if reset else ''}")
        else:
            bits.append(f"{name}: {p.get('status') or 'ok'}")
    return "；".join(bits) if bits else "用量查询完成。"


def try_direct_tool(text: str) -> str | None:
    """Optional hard-coded single-tool shortcut (off by default).

    Prefer the iterative tool-calling loop so the model can chain tools and
    use agent-scoped memory. Set AIPC_DAILY_DIRECT_TOOLS=1 only for emergency
    speed when ornith is cold.
    """
    # Default on: clear single-tool asks must not wait for ornith tool-loop.
    # Set AIPC_DAILY_DIRECT_TOOLS=0 to force full iterative agent always.
    if os.environ.get("AIPC_DAILY_DIRECT_TOOLS", "1") in ("0", "false", "no", "off"):
        return None
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.lower()

    # usage / quota
    if any(k in raw for k in ("用量", "额度", "額度")) or any(
        k in low for k in ("quota", "usage", "token")
    ):
        ux_bridge.progress("直接查用量…", source="daily-direct")
        try:
            result = usage_lookup.invoke({"providers": ""})
        except Exception as exc:  # noqa: BLE001
            return f"查用量失败：{exc}"
        return _format_usage_speech(result if isinstance(result, dict) else {"status": "error"})

    # calendar today-ish
    if any(k in raw for k in ("日历", "日曆", "日程", "会议", "會議", "行程")) or "calendar" in low:
        ux_bridge.progress("直接查日曆…", source="daily-direct")
        try:
            result = calendar_lookup.invoke({"query": raw[:80]})
        except Exception as exc:  # noqa: BLE001
            return f"查日曆失败：{exc}"
        if not isinstance(result, dict):
            return "日曆查询无结果。"
        if result.get("status") == "not_configured":
            return "日曆工具还没配置好。"
        if result.get("status") != "ok":
            return f"日曆查询：{result.get('detail') or result.get('status')}"
        # Best-effort speech summary
        events = result.get("events") or result.get("items") or result.get("data") or []
        if isinstance(events, list) and events:
            titles = []
            for e in events[:5]:
                if isinstance(e, dict):
                    titles.append(str(e.get("summary") or e.get("title") or e)[:40])
                else:
                    titles.append(str(e)[:40])
            return "今天的安排：" + "；".join(titles)
        return str(result.get("detail") or result.get("message") or "没有找到相关日程。")[:200]

    # simple web search — only short explicit forms (avoid eating complex research)
    if re.search(r"^(搜一下|搜索|搜尋|查一下)\s*.{1,40}$", raw) or re.search(
        r"^(search|web search)\s+.{1,40}$", low
    ):
        q = re.sub(r"^(搜一下|搜索|搜尋|查一下|search|web search)\s*", "", raw, flags=re.I).strip()
        if not q or any(k in q for k in ("用量", "日历", "日曆", "代码", "代碼")):
            return None
        ux_bridge.progress(f"直接搜尋：{q[:30]}", source="daily-direct")
        try:
            result = search.invoke({"query": q, "limit": 3})
        except Exception as exc:  # noqa: BLE001
            return f"搜索失败：{exc}"
        if not isinstance(result, dict):
            return "搜索无结果。"
        if result.get("status") in ("not_configured", "error"):
            return f"搜索：{result.get('detail') or result.get('status')}"
        hits = result.get("results") or result.get("items") or []
        if isinstance(hits, list) and hits:
            lines = []
            for h in hits[:3]:
                if isinstance(h, dict):
                    lines.append(str(h.get("title") or h.get("url") or h)[:60])
                else:
                    lines.append(str(h)[:60])
            return "搜索结果：" + "；".join(lines)
        return "没有搜到相关结果。"

    return None


def _memory_parts(state: DailyAssistantState) -> list[str]:
    # Isolated lane: daily tools never see coder/hermes memories
    remembered = memory.recall(
        state["text"], state["session_id"], agent=memory.AGENT_DAILY
    )
    parts = []
    if remembered:
        parts.append(f"Relevant daily-agent memories (not coding):\n{remembered}")
    try:
        from aipc_agent import agent_context

        hist = agent_context.format_history(state["session_id"], memory.AGENT_DAILY)
        if hist:
            parts.append(f"Recent daily-agent turns:\n{hist}")
    except Exception:
        pass
    return parts


def _memory_messages(state: DailyAssistantState) -> list[SystemMessage]:
    parts = _memory_parts(state)
    if not parts:
        return []
    return [SystemMessage(content="\n\n".join(parts))]


def _flatten_for_chat_template(messages: list) -> list:
    """coder-agentic / Qwen templates require a single leading system message.

    Multiple role=system blocks → 400 "System message must be at the beginning".
    Merge all system content into one head SystemMessage; keep other roles.
    """
    sys_parts: list[str] = []
    rest: list = []
    for m in messages or []:
        role = getattr(m, "type", None) or getattr(m, "role", None)
        # LangChain: SystemMessage.type == "system"
        if role == "system" or m.__class__.__name__ == "SystemMessage":
            chunk = text_of(getattr(m, "content", m)).strip()
            if chunk:
                sys_parts.append(chunk)
        else:
            rest.append(m)
    out: list = []
    if sys_parts:
        out.append(SystemMessage(content="\n\n".join(sys_parts)))
    out.extend(rest)
    return out


def _seed(state: DailyAssistantState) -> dict:
    # One system only — required by coder-agentic chat template
    sys_parts = [SYSTEM_PROMPT, *_memory_parts(state)]
    return {
        "messages": [
            SystemMessage(content="\n\n".join(p for p in sys_parts if p)),
            HumanMessage(content=state["text"]),
        ]
    }


def _job_progress(detail: str, *, thinking: str = "") -> None:
    """Push to background job when present; always update overlay."""
    try:
        from aipc_agent import task_jobs

        if task_jobs.current_job_id():
            task_jobs.job_update(detail, thinking=thinking or detail)
            return
    except Exception:
        pass
    ux_bridge.progress(detail[:120], source="daily-assistant")


def _agent(state: DailyAssistantState) -> dict:
    _job_progress("日曆/工具助手思考中…", thinking="决定下一步工具")
    try:
        msgs = _flatten_for_chat_template(list(state.get("messages") or []))
        reply = _chat_model().invoke(msgs)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: daily LLM fail: {exc}", flush=True)
        from langchain_core.messages import AIMessage

        msg = AIMessage(
            content="本地工具模型暂时连不上，请稍后再试（检查 LiteLLM / 工具模型）。"
        )
        return {"messages": [msg]}
    # ornith-35b (a reasoning model) returns content as a block list
    # (e.g. {"type": "thinking", ...}); llama-server rejects that shape if
    # this message is ever re-sent as history on the next tool-loop turn
    # ("unsupported content[].type" — hardware-verified 2026-07-06).
    # Normalize before it lands in state; tool_calls are untouched.
    reply.content = text_of(reply.content)
    names = ux_bridge.tool_names_from_message(reply)
    if names:
        label = ux_bridge.humanize_tools(names)
        _job_progress(label, thinking=label)
    return {"messages": [reply]}


def _tools_node(state: DailyAssistantState) -> dict:
    """Run tools with visible UX so the user is not left in a silent wait."""
    last = (state.get("messages") or [None])[-1]
    names = ux_bridge.tool_names_from_message(last) if last is not None else []
    label = ux_bridge.humanize_tools(names)
    _job_progress(label, thinking=f"执行 {label}")
    return ToolNode(TOOLS).invoke(state)


def _finish(state: DailyAssistantState) -> dict:
    text = text_of(state["messages"][-1].content)
    sid = state["session_id"]
    memory.internalize(
        state["text"], text, sid, agent=memory.AGENT_DAILY, kind="daily"
    )
    try:
        from aipc_agent.skill_learn import maybe_learn_async

        maybe_learn_async(
            state["text"], text, session_id=sid, kind="daily", agent="daily"
        )
    except Exception:
        pass
    try:
        from aipc_agent import agent_context

        agent_context.append_turn(sid, memory.AGENT_DAILY, "user", state["text"])
        agent_context.append_turn(sid, memory.AGENT_DAILY, "assistant", text)
        agent_context.append_turn(sid, memory.AGENT_CHAT, "user", state["text"])
        agent_context.append_turn(sid, memory.AGENT_CHAT, "assistant", text[:500])
    except Exception:
        pass
    return {"text": text, "session_id": sid}


def daily_assistant():
    graph = StateGraph(DailyAssistantState)
    graph.add_node("seed", _seed)
    graph.add_node("agent", _agent)
    graph.add_node("tools", _tools_node)
    graph.add_node("finish", _finish)
    graph.set_entry_point("seed")
    graph.add_edge("seed", "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: "finish"})
    graph.add_edge("tools", "agent")
    graph.add_edge("finish", END)
    return graph.compile()
