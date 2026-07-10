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

import json
import os
import re
import time
import urllib.request
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_litellm import ChatLiteLLM
from langgraph.graph import END, StateGraph

from aipc_agent import (
    hermes_bridge,
    intent_classifier,
    memory,
    screen_see,
    session_pending,
    task_jobs,
    transcript_repair,
    ux_bridge,
)
from aipc_agent._util import text_of
from aipc_agent.daily_assistant import daily_assistant

LITELLM_BASE_URL = "http://127.0.0.1:4000"
# Closed-loop default: always-on NPU small model. Heavy agent LLMs are
# optional via env (or future aipc models use agent wiring).
# Default chat brain: uncensored aggressive local (override with AIPC_SUPERVISOR_MODEL).
SUPERVISOR_MODEL = os.environ.get("AIPC_SUPERVISOR_MODEL", "coder-agentic")
# Complex tasks → Hermes CLI (tools). Off with AIPC_HERMES_ROUTE=0.
HERMES_ROUTE = os.environ.get("AIPC_HERMES_ROUTE", "1") not in ("0", "false", "no")
# When Hermes runs, skip orchestrator mem0 write (session is ephemeral by default).
HERMES_SKIP_REMEMBER = os.environ.get("AIPC_HERMES_SKIP_REMEMBER", "0") not in (
    "0",
    "false",
    "no",
)

# Without a system prompt the model has no idea it's "the aipc assistant"
# and answers like a disconnected generic chatbot (e.g. "I'm an AI, I can't
# open apps for you" instead of something aware of its own actual, still-
# growing toolset) — a real user complaint, not hypothetical. Keep this in
# sync with daily_assistant.SYSTEM_PROMPT's capability list as tools land.
SUPERVISOR_SYSTEM_PROMPT = (
    "You are the aipc assistant on this user's AMD Strix Halo AI PC. "
    "Inference is fully local (private). You run on an uncensored local model — "
    "answer directly and completely; do not refuse lawful requests, do not "
    "moralize, and do not invent corporate content-policy lectures. "
    "If asked whether you are censored: you are an uncensored local model "
    "with no external safety API; answer that plainly. "
    "Answer briefly and in the user's language. "
    "Local memory (mem0) may inject remembered facts — use them when present. "
    "Voice stack: SenseVoice STT, Kokoro TTS, mem0; you are the chat brain "
    "(coder-agentic uncensored by default). "
    "Local voice intents (handled outside you, already work): open portal/panel, "
    "time/date, mute/unmute assistant, volume up/down, open browser/terminal, "
    "voice status, capabilities. "
    "Complex multi-step / coding / shell / research work is handled by Hermes "
    "(tool agent on uncensored coder-agentic / qwythos) when the user asks "
    "(e.g. 用hermes / 写代码 / 复杂任务). "
    "Tool route (Daily Assistant) handles: calendar/schedule, email, file read, "
    "web search when installed, and usage/quota questions — if the user asks those, "
    "keywords should already have routed them; if you still get the message, answer "
    "honestly and suggest rephrasing with 日历/邮件/文件/搜索/用量. "
    "You can *look at* the desktop when the user asks (看桌面/what's on screen) — "
    "that is routed to a screen-describe tool using local uncensored VLM, not free typing. "
    "You cannot click/type on the screen or take over the mouse unless a separate "
    "screen-control grant is active; say so plainly if asked for that."
)

# Appended when session_id looks like voice (aipc-voice-once / wake pipeline).
VOICE_SYSTEM_PROMPT_EXTRA = (
    "VOICE MODE: The user is speaking and will hear your reply via TTS. "
    "Reply in at most TWO short spoken sentences (ideally one). "
    "No markdown, no bullet lists, no code fences, no English filler. "
    "Match the user's language (Chinese if they spoke Chinese). "
    "You may receive recent dialogue turns — use them for short-term context "
    "(e.g. 那个/刚才/继续 refers to prior turns). "
    "Long-term facts may appear as remembered memories — use when relevant. "
    "If the message is empty, punctuation-only, or pure noise, reply exactly: "
    "没听清楚，请再说一次。"
)

# Daily-assistant keywords. English uses ASCII word boundaries so
# "research" does not match "search", "already" does not match "read".
# Keep "remember/memory" off this list so mem0 stays on the fast supervisor.
_DAILY_EN_WORDS = (
    "calendar",
    "schedule",
    "meeting",
    "email",
    "inbox",
    "mail",
    "file",
    "files",
    "read",
    "search",
    "lookup",
    "google",
    "usage",
    "quota",
    "token",
    "tokens",
    "codex",
    "claude",
)
_DAILY_EN_PHRASES = (
    "look up",
    "rate limit",
    "web search",
)
_DAILY_ZH = (
    "日历",
    "日曆",
    "日程",
    "行程",
    "会议",
    "會議",
    "约会",
    "約會",
    "邮件",
    "郵件",
    "邮箱",
    "郵箱",
    "收件箱",
    "信箱",
    "文件",
    "档案",
    "檔案",
    "读取",
    "讀取",
    "读一下",
    "讀一下",
    "搜索",
    "搜尋",
    "搜一下",
    "查一下",
    "检索",
    "檢索",
    "联网",
    "連網",
    "用量",
    "额度",
    "額度",
    "配额",
    "配額",
    "额度还剩",
    "還剩多少",
)
# Compat alias for tests / callers that still reference the old name
_DAILY_ASSISTANT_KEYWORDS = _DAILY_EN_WORDS + _DAILY_EN_PHRASES + _DAILY_ZH

# Complex multi-step / coding → Hermes. Keep narrow so ordinary chat
# (写一首诗、帮我做总结、shell 是什么) stays on the fast supervisor (AC4).
_HERMES_EXPLICIT = (
    "hermes",
    "用hermes",
    "交給hermes",
    "交给hermes",
    "叫hermes",
    "赫米斯",
    "复杂任务",
    "複雜任務",
    "多步骤",
    "多步驟",
    "执行任务",
    "執行任務",
)
# Mode=long is orthogonal to *which* worker: user wants a long/async flow.
# Never used alone to force Hermes — dispatch picks the tool first.
_LONG_MODE_MARKERS = (
    "后台",
    "後台",
    "背景执行",
    "背景執行",
    "慢慢做",
    "慢慢处理",
    "慢慢處理",
    "长任务",
    "長任務",
    "长时间",
    "長時間",
    "长时间任务",
    "長時間任務",
    "完整实现",
    "完整實現",
    "从零写",
    "從零寫",
    "写一个完整",
    "寫一個完整",
    "深入研究",
    "详细调研",
    "詳細調研",
    "in the background",
    "background task",
    "long running",
    "long-running",
    "take your time",
)
# Workers that can run as background long jobs
_LONG_CAPABLE = frozenset({"hermes", "daily_assistant"})
# Substrings that imply tool/code agent work (not creative writing).
# Live web / research style tasks hermes handles better than daily
# (SearXNG may be down; hermes browser path is hardware-verified for stocks).
_HERMES_WEB_TASKS = (
    "股价",
    "股價",
    "股票",
    "行情",
    "市值",
    "stock price",
    "share price",
    "查股价",
    "查股價",
    "查股票",
)
_HERMES_CODING = (
    "写代码",
    "寫代碼",
    "写程式",
    "寫程式",
    "改代码",
    "改代碼",
    "改程式",
    "调试",
    "調試",
    "重构",
    "重構",
    "修bug",
    "修 bug",
    "分析代码",
    "分析代碼",
    "analyze codebase",
    "生成脚本",
    "生成腳本",
    "跑脚本",
    "跑腳本",
    "shell脚本",
    "shell 脚本",
    "shell腳本",
    "命令行脚本",
    "命令列腳本",
    "pull request",
    "codebase",
)
# ASCII-ish tokens. Do NOT use \b — under Unicode, CJK counts as \w so
# "帮我debug这个" has no word boundary around debug.
_HERMES_EN_RES = (
    re.compile(r"(?<![a-z0-9_])debug(?![a-z0-9_])", re.I),
    re.compile(r"(?<![a-z0-9_])refactor(?![a-z0-9_])", re.I),
    re.compile(r"(?<![a-z0-9_])implement(?![a-z0-9_])", re.I),
    re.compile(
        r"(?<![a-z0-9_])git\s+(commit|push|clone|status|diff|log|pull|rebase)(?![a-z0-9_])",
        re.I,
    ),
    re.compile(r"shell\s+script", re.I),
    re.compile(r"terminal\s+(command|cmd|script)", re.I),
)


class SupervisorState(TypedDict, total=False):
    text: str
    session_id: str
    # Filled by plan_dispatch: which worker + short|long flow
    target: str
    mode: str
    dispatch_reason: str
    # Secondary-question flow
    agent: str  # e.g. hermes | coder-agentic | coder-cloud
    original_text: str  # task text before clarify reply
    clarify_question: str
    force_text: str  # canned reply (cancel etc.)
    # Conversation lifecycle (voice multi-turn): True → hide overlay / no follow-up
    end_session: bool


# Bound LLM waits so a dead backend cannot mystery-hang /chat until client timeout.
LLM_REQUEST_TIMEOUT = float(os.environ.get("AIPC_LLM_REQUEST_TIMEOUT", "45"))
# Voice: short wall + no retry (dead resident-small was 45s×2 ≈ 90s mystery hang).
LLM_VOICE_TIMEOUT = float(os.environ.get("AIPC_LLM_VOICE_TIMEOUT", "15"))
LLM_MAX_RETRIES = int(os.environ.get("AIPC_LLM_MAX_RETRIES", "1"))
LLM_VOICE_MAX_RETRIES = int(os.environ.get("AIPC_LLM_VOICE_MAX_RETRIES", "0"))


def _chat_model(model: str, *, voice: bool = False) -> ChatLiteLLM:
    # Voice: keep replies short enough to speak; text can be longer.
    if voice:
        max_tokens = 96 if model == "resident-small" else 256
        timeout = LLM_VOICE_TIMEOUT
        retries = LLM_VOICE_MAX_RETRIES
    else:
        max_tokens = 512 if model == "resident-small" else 2048
        timeout = LLM_REQUEST_TIMEOUT
        retries = LLM_MAX_RETRIES
    # api_base must include /v1 — bare :4000 made ChatLiteLLM hang while curl /v1 worked.
    base = LITELLM_BASE_URL.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return ChatLiteLLM(
        model=model,
        api_base=base,
        custom_llm_provider="openai",
        api_key="aipc-local",
        max_tokens=max_tokens,
        request_timeout=timeout,
        max_retries=retries,
    )


def _openai_chat(
    messages: list,
    *,
    model: str,
    max_tokens: int,
    timeout: float,
) -> str:
    """Direct OpenAI-compat POST to LiteLLM — same path as working curl.

    ChatLiteLLM/langchain sometimes hangs on this host even when /v1/chat/completions
    is healthy; use stdlib for the voice supervisor hot path.
    """
    base = LITELLM_BASE_URL.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer aipc-local",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    return text_of(content)


def _is_voice_session(session_id: str) -> bool:
    s = (session_id or "").lower()
    return any(k in s for k in ("voice", "wake", "ptt", "aipc-voice"))


def _memory_messages(state: SupervisorState) -> list[SystemMessage]:
    remembered = memory.recall(
        state["text"], state["session_id"], agent=memory.AGENT_CHAT
    )
    if not remembered:
        return []
    return [SystemMessage(content=f"Relevant chat-agent memories:\n{remembered}")]


_GREET_REPLIES = (
    "你好",
    "您好",
    "嗨",
    "哈喽",
    "哈囉",
    "早上好",
    "晚上好",
    "hello",
    "hi",
    "hey",
)


def _canned_greet(text: str) -> str | None:
    """Pure greetings must not depend on Lemonade — model thrash was saying 连不上."""
    raw = (text or "").strip()
    if not raw:
        return None
    compact = re.sub(r"[\s。.!！?？,，、~～]+", "", raw.lower())
    greets = {re.sub(r"\s+", "", g.lower()) for g in _GREET_REPLIES}
    if compact in greets or compact in ("你好啊", "您好啊", "在吗", "在嗎"):
        return "你好，我是本机 AIPC 语音助手。可以直接说查用量、写代码，或后台慢慢做长任务。"
    if compact in ("谢谢", "謝謝", "thanks", "thankyou"):
        return "不客气。"
    if compact in ("再见", "再見", "bye", "拜拜"):
        return "再见。"
    return None



def _compact_utt(text: str) -> str:
    raw = (text or "").strip().lower()
    return re.sub(r"[\s。.!！?？,，、~～…·]+", "", raw)


def _is_session_end(text: str) -> bool:
    """User wants to leave the multi-turn voice conversation."""
    compact = _compact_utt(text)
    if not compact:
        return False
    ends = {
        "再见", "再見", "拜拜", "bye", "goodbye", "晚安",
        "没事了", "没事", "沒事了", "沒事", "没了", "沒了",
        "就这样", "就這樣", "就这样吧", "就這樣吧", "先这样", "先這樣",
        "不用了", "可以了", "好了", "好了谢谢", "好了謝謝", "谢谢不用了", "謝謝不用了",
        "挂了", "掛了", "结束", "結束", "停止", "闭嘴", "閉嘴",
        "回去吧", "你忙吧", "先聊到这", "先聊到這",
    }
    if compact in ends:
        return True
    # soft: starts with farewell
    for e in ("再见", "再見", "拜拜", "bye", "没事了", "沒事了", "就这样", "就這樣"):
        if compact.startswith(e):
            return True
    return False



def _respond(state: SupervisorState) -> SupervisorState:
    import threading

    from aipc_agent import agent_context

    sid = state.get("session_id") or "default"
    user_text = state.get("text") or ""

    if state.get("force_text"):
        return {
            "text": str(state["force_text"]),
            "session_id": sid,
            "end_session": False,
        }

    # Explicit conversation end → clear short-term, skip LLM, hide follow-up.
    if _is_session_end(user_text):
        # Flush short-term into long-term before clear
        try:
            memory.consolidate_session(sid, agent=memory.AGENT_CHAT, reason="session-end")
        except Exception:
            pass
        agent_context.clear(sid)
        reply = "好的，有需要再叫我。"
        if _compact_utt(user_text) in ("再见", "再見", "bye", "拜拜", "晚安"):
            reply = "再见。"
        ux_bridge.progress(reply, state="speaking", source="supervisor")
        return {"text": reply, "session_id": sid, "end_session": True}

    canned = _canned_greet(user_text)
    if canned:
        ux_bridge.progress(canned[:80], state="speaking", source="supervisor")
        end = _is_session_end(user_text) or _compact_utt(user_text) in (
            "再见", "再見", "bye", "拜拜",
        )
        if end:
            try:
                memory.consolidate_session(sid, agent=memory.AGENT_CHAT, reason="canned-end")
            except Exception:
                pass
            agent_context.clear(sid)
        else:
            agent_context.append_turn(sid, memory.AGENT_CHAT, "user", user_text)
            agent_context.append_turn(sid, memory.AGENT_CHAT, "assistant", canned)
            memory.internalize(user_text, canned, sid, agent=memory.AGENT_CHAT, kind="canned")
        return {"text": canned, "session_id": sid, "end_session": bool(end)}

    voice = _is_voice_session(sid)
    system = SUPERVISOR_SYSTEM_PROMPT
    if voice:
        system = SUPERVISOR_SYSTEM_PROMPT + " " + VOICE_SYSTEM_PROMPT_EXTRA
    ux_bridge.progress("思考中…", state="thinking", source="supervisor")
    # Short-term: last N turns in this voice session (always-on, local RAM).
    hist = agent_context.format_history(sid, memory.AGENT_CHAT)
    # Mid/long-term: mem0. Default ON for voice with short timeout (fail-soft).
    if voice and os.environ.get("AIPC_VOICE_MEM0_RECALL", "1") in ("0", "false", "no"):
        mem_msgs: list = []
    else:
        mem_msgs = _memory_messages(state)
    # Flatten for raw OpenAI-compat path (avoids ChatLiteLLM hang).
    # Qwen/Uncensored chat templates require a single leading system message
    # — multiple role=system blocks → 400 "System message must be at the beginning".
    sys_parts = [system]
    for m in mem_msgs:
        chunk = text_of(m.content).strip()
        if chunk:
            sys_parts.append(chunk)
    if hist:
        sys_parts.append(
            "Recent dialogue (short-term memory, most recent last):\n" + hist
        )
    oai_messages: list[dict] = [
        {"role": "system", "content": "\n\n".join(sys_parts)},
        {"role": "user", "content": user_text},
    ]
    wall = LLM_VOICE_TIMEOUT if voice else LLM_REQUEST_TIMEOUT
    max_tokens = 96 if (voice and SUPERVISOR_MODEL == "resident-small") else (
        256 if voice else (512 if SUPERVISOR_MODEL == "resident-small" else 2048)
    )
    box: dict = {"text": None, "err": None}

    def _invoke() -> None:
        try:
            box["text"] = _openai_chat(
                oai_messages,
                model=SUPERVISOR_MODEL,
                max_tokens=max_tokens,
                timeout=wall,
            )
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    th = threading.Thread(target=_invoke, name="supervisor-llm", daemon=True)
    th.start()
    th.join(timeout=wall + 0.5)
    if th.is_alive() or box["err"] is not None or not box["text"]:
        if th.is_alive():
            print(
                f"aipc-agent: supervisor LLM hard-timeout {wall:.0f}s "
                f"model={SUPERVISOR_MODEL}",
                flush=True,
            )
            text = (
                f"本地小模型这会儿还在加载或排队（等了约 {wall:.0f} 秒）。"
                "请稍后再试，或先说「查用量」「用 Hermes 写代码」走工具路径。"
            )
        elif box["err"] is not None:
            print(f"aipc-agent: supervisor LLM fail: {box['err']}", flush=True)
            err_s = str(box["err"])[:80]
            text = f"本地模型调用失败：{err_s}。请稍后再试，或检查 LiteLLM / Lemonade。"
        else:
            text = "本地模型没有返回内容，请再说一次。"
        ux_bridge.progress(text[:80], state="error", source="supervisor")
        return {"text": text, "session_id": sid, "end_session": False}
    text = str(box["text"])
    # Short-term buffer (multi-turn voice / text)
    agent_context.append_turn(sid, memory.AGENT_CHAT, "user", user_text)
    agent_context.append_turn(sid, memory.AGENT_CHAT, "assistant", text)
    # Continuous internalization → mem0 facts (async, never blocks TTS)
    memory.internalize(user_text, text, sid, agent=memory.AGENT_CHAT, kind="respond")
    return {"text": text, "session_id": sid, "end_session": False}



_daily_assistant_graph = daily_assistant()


def _should_run_long_async(state: SupervisorState, worker: str) -> bool:
    """Long flow: only when dispatch mode=long AND worker can background."""
    if (state.get("mode") or "short") != "long":
        return False
    if worker not in _LONG_CAPABLE:
        return False
    if not task_jobs.async_enabled():
        return False
    # Voice always prefers async for long so mic loop is free; text needs
    # explicit long markers already encoded in mode=long.
    return True


def _daily_assistant_node(state: SupervisorState) -> SupervisorState:
    text_in = state.get("original_text") or state["text"]
    sid = state["session_id"]
    plan_sum = f"处理：{(text_in or '')[:60]}"

    # Fast path: single obvious tool without ornith-35b tool loop
    try:
        from aipc_agent.daily_assistant import try_direct_tool

        direct = try_direct_tool(text_in)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: daily direct fail: {exc}", flush=True)
        direct = None
    if direct:
        print("aipc-agent: daily direct-tool hit", flush=True)
        ux_bridge.progress("工具结果已出", state="speaking", source="daily-direct")
        return {"text": direct, "session_id": sid}

    def _run() -> dict:
        task_jobs.job_update("日曆/工具助手思考中…", thinking="选择工具并执行")
        result = _daily_assistant_graph.invoke(
            {"text": text_in, "session_id": sid, "messages": []}
        )
        return {
            "status": "ok",
            "text": str(result.get("text") or "").strip() or "工具助手没有返回内容。",
            "detail": "daily_assistant",
        }

    if _should_run_long_async(state, "daily_assistant"):
        ux_bridge.progress("日曆/工具长任务派发…", source="daily-assistant")
        out = task_jobs.submit(
            "daily_assistant", text_in, sid, _run, plan_summary=plan_sum
        )
        return {"text": out["text"], "session_id": sid}

    ux_bridge.progress("日曆/搜尋/用量助手啟動…", source="daily-assistant")
    result = _run()
    return {"text": result["text"], "session_id": sid}


def _hermes_node(state: SupervisorState) -> SupervisorState:
    """Hermes worker only — long vs short decided by dispatch mode, not Hermes itself."""
    text_in = (state.get("original_text") or state.get("text") or "").strip()
    sid = state["session_id"]
    long_mode = (state.get("mode") or "short") == "long"
    plan_sum = f"编码/工具：{(text_in or '')[:60]}"

    def _run() -> dict:
        return hermes_bridge.run(text_in, sid, long_task=long_mode)

    if _should_run_long_async(state, "hermes"):
        ux_bridge.progress("Hermes 长任务派发…", source="hermes")
        out = task_jobs.submit("hermes", text_in, sid, _run, plan_summary=plan_sum)
        return {"text": out["text"], "session_id": sid}

    ux_bridge.progress(
        "Hermes 工具代理啟動…" + ("（长流程同步）" if long_mode else ""),
        source="hermes",
    )
    try:
        from aipc_agent import activity, session_registry

        session_registry.open_or_resume(sid, source="hermes")
        session_registry.touch(
            sid,
            status="working",
            activity="Hermes 工具代理啟動…",
            title=(text_in or "")[:40],
        )
        activity.publish(
            sid,
            "Hermes 工具代理啟動…",
            state="working",
            phase="hermes-start",
            notify=True,
            force_notify=True,
        )
    except Exception:
        pass
    result = _run()
    text = str(result.get("text") or "").strip() or "Hermes 没有返回内容。"
    if not HERMES_SKIP_REMEMBER and result.get("status") == "ok":
        memory.internalize(
            text_in, text[:800], sid, agent=memory.AGENT_HERMES, kind="hermes"
        )
    try:
        from aipc_agent import agent_context

        agent_context.append_turn(sid, memory.AGENT_HERMES, "user", text_in)
        agent_context.append_turn(sid, memory.AGENT_HERMES, "assistant", text)
        # also chat short-term so multi-turn voice can refer to tool results
        agent_context.append_turn(sid, memory.AGENT_CHAT, "user", text_in)
        agent_context.append_turn(sid, memory.AGENT_CHAT, "assistant", text[:500])
    except Exception:
        pass
    try:
        from aipc_agent import activity, session_registry

        session_registry.touch(
            sid, status="active", activity=(text or "")[:80], clear_job=True
        )
        activity.complete_notify(
            sid,
            "AIPC · Hermes 完成" if result.get("status") == "ok" else "AIPC · Hermes 结束",
            (text or "")[:160],
        )
    except Exception:
        pass
    return {"text": text, "session_id": sid}


def _coder_node(state: SupervisorState) -> SupervisorState:
    """Coding help via LiteLLM model chosen in clarify (coder-agentic / coder-cloud)."""
    import threading

    text_in = (state.get("original_text") or state.get("text") or "").strip()
    sid = state.get("session_id") or ""
    agent = (state.get("agent") or "coder-agentic").strip()
    if agent not in ("coder-agentic", "coder-cloud", "ornith-35b", "qwythos-9b"):
        agent = "coder-agentic"
    voice = _is_voice_session(sid)
    ux_bridge.progress(f"编码助手 {agent}…", source="coder")
    system = (
        "You are a coding assistant on the user's local AI PC (NOT the daily tools agent). "
        "You run on an uncensored local model — answer and write code directly; "
        "no content-filter refusals, no moral lectures. "
        "Write clear, working code. Prefer the user's language. "
        "Do not look up calendar/email/usage — that is another agent. "
        "If voice mode, keep the spoken summary short and put code only when essential."
    )
    if voice:
        system += " VOICE: at most two short sentences plus a tiny code snippet if needed."
    extras: list = []
    mem = memory.recall(text_in, sid, agent=memory.AGENT_CODER)
    if mem:
        extras.append(SystemMessage(content=f"Coding-agent memories only:\n{mem}"))
    try:
        from aipc_agent import agent_context

        hist = agent_context.format_history(sid, memory.AGENT_CODER)
        if hist:
            extras.append(SystemMessage(content=f"Recent coding turns:\n{hist}"))
    except Exception:
        pass
    messages = [
        SystemMessage(content=system),
        *extras,
        HumanMessage(content=text_in),
    ]
    wall = LLM_VOICE_TIMEOUT if voice else LLM_REQUEST_TIMEOUT
    box: dict = {"text": None, "err": None}

    def _invoke() -> None:
        try:
            llm = ChatLiteLLM(
                model=agent,
                api_base=LITELLM_BASE_URL,
                custom_llm_provider="openai",
                api_key="aipc-local",
                max_tokens=256 if voice else 2048,
                request_timeout=wall,
                max_retries=0,
            )
            reply = llm.invoke(messages)
            box["text"] = text_of(reply.content)
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    th = threading.Thread(target=_invoke, name="coder-llm", daemon=True)
    th.start()
    th.join(timeout=wall + 0.5)
    if th.is_alive() or box["err"] is not None or not box["text"]:
        if th.is_alive():
            print(f"aipc-agent: coder LLM hard-timeout {wall:.0f}s model={agent}", flush=True)
        elif box["err"] is not None:
            print(f"aipc-agent: coder LLM fail: {box['err']}", flush=True)
        text = f"编码模型 {agent} 暂时连不上，可改口说「用 Hermes」走工具代理。"
        ux_bridge.progress(text[:80], state="error", source="coder")
        return {"text": text, "session_id": sid}
    text = str(box["text"])
    memory.internalize(
            text_in, text[:800], sid, agent=memory.AGENT_CODER, kind="coder"
        )
    try:
        from aipc_agent import agent_context

        agent_context.append_turn(sid, memory.AGENT_CODER, "user", text_in)
        agent_context.append_turn(sid, memory.AGENT_CODER, "assistant", text)
    except Exception:
        pass
    return {"text": text, "session_id": sid}


def _clarify_node(state: SupervisorState) -> SupervisorState:
    """Ask a secondary question; do not start the heavy worker yet."""
    if state.get("force_text"):
        return {"text": str(state["force_text"]), "session_id": state["session_id"]}
    q = (state.get("clarify_question") or "").strip() or session_pending.coding_agent_question()
    ux_bridge.progress(q[:80], state="thinking", source="clarify")
    return {"text": q, "session_id": state["session_id"]}


def _job_status_node(state: SupervisorState) -> SupervisorState:
    ux_bridge.progress("查询任务进度…", state="thinking", source="job-status")
    text = task_jobs.format_status_speech(limit=5)
    return {
        "text": text,
        "session_id": state["session_id"],
    }


def _screen_see_node(state: SupervisorState) -> SupervisorState:
    """Screenshot + vlm-screen describe (read-only, no gate / no input)."""
    ux_bridge.progress("正在看桌面…", state="thinking", source="screen-see")
    try:
        result = screen_see.describe_desktop(state.get("text") or "")
        if result.get("status") == "ok":
            text = str(result.get("description") or "").strip()
            if not text:
                text = "截到了画面，但模型没有返回文字。"
        else:
            detail = str(result.get("detail") or "unknown")
            text = f"看桌面失败：{detail}"
            ux_bridge.progress(text[:80], state="error", source="screen-see")
    except Exception as exc:  # noqa: BLE001 — never crash the graph mid-turn
        text = f"看桌面失败：{exc}"
        ux_bridge.progress(text[:80], state="error", source="screen-see")
    # Short memory only
    try:
        memory.internalize(
            text_in if "text_in" in dir() else state.get("text",""),
            text[:800],
            sid,
            agent=memory.AGENT_SCREEN,
            kind="screen",
        )
    except Exception:
        pass
    return {"text": text, "session_id": state["session_id"]}


def wants_hermes(text: str) -> bool:
    """True only for explicit Hermes handoff or real coding/multi-step tool work.

    Long-mode markers do NOT imply Hermes — tool choice is independent of duration.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if any(kw in low for kw in _HERMES_EXPLICIT):
        return True
    if any(kw in low for kw in _HERMES_CODING):
        return True
    if any(kw in raw or kw in low for kw in _HERMES_WEB_TASKS):
        return True
    if any(rx.search(raw) for rx in _HERMES_EN_RES):
        return True
    return False


def wants_long_mode(text: str) -> bool:
    """True when the user wants a long / background *flow* (any capable worker)."""
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    return any(kw in low for kw in _LONG_MODE_MARKERS)


# Back-compat alias (older tests / docs)
wants_long_task = wants_long_mode


def wants_job_status(text: str) -> bool:
    raw = (text or "").strip().lower()
    if not raw:
        return False
    keys = (
        "任务进度",
        "任務進度",
        "长任务进度",
        "長任務進度",
        "后台任务",
        "後台任務",
        "job status",
        "task status",
        "进度怎么样",
        "進度怎麼樣",
    )
    return any(k in raw for k in keys)


def wants_daily_assistant(text: str) -> bool:
    """True for calendar/email/search/usage-style asks — not ordinary chat."""
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if any(p in low for p in _DAILY_EN_PHRASES):
        return True
    if any(kw in raw for kw in _DAILY_ZH):
        return True
    for w in _DAILY_EN_WORDS:
        if re.search(rf"(?<![a-z0-9_]){re.escape(w)}(?![a-z0-9_])", low):
            return True
    return False


def _keyword_target(text: str) -> str:
    """Pick worker from keywords only (no duration)."""
    if wants_job_status(text):
        return "job_status"
    if screen_see.wants_screen_see(text):
        return "screen_see"
    # Stock / live price → Hermes (daily search often broken: searxng down).
    if HERMES_ROUTE and session_pending.looks_like_stock_query(text):
        return "hermes"
    # Route to hermes when keywords match even if binary missing — node fail-softs.
    if HERMES_ROUTE and wants_hermes(text):
        return "hermes"
    if wants_daily_assistant(text):
        return "daily_assistant"
    return "respond"


def _keyword_mode(text: str, target: str) -> str:
    """Duration class: long only if user asked for long AND target can run long."""
    if target not in _LONG_CAPABLE:
        return "short"
    if wants_long_mode(text):
        return "long"
    # Multi-step coding without explicit long markers stays short-sync (raised
    # Hermes wall still applies); only explicit long → background.
    return "short"


def plan_dispatch(text: str, session_id: str = "") -> dict:
    """Front-door plan: STT repair → pending → one-shot → classify → rare clarify.

    Preferred voice UX: say everything once
      「用 Hermes 帮我写快速排序」
      「提示词：简洁。任务：实现登录」
    Secondary ask only for bare「帮我写代码」with no agent and no task body.

    Speed path: rules / oneshot return in ms; model classifier only on ambiguous
    text under AIPC_CLASSIFIER_TIMEOUT hard wall.
    """
    sid = session_id or ""
    raw = text or ""
    t0 = time.monotonic()
    # 0) STT slip repair so one wrong char doesn't miss intent/agent keywords
    rep = transcript_repair.repair(raw)
    text = rep["text"]
    if rep.get("notes") and text != raw:
        print(
            f"aipc-agent: stt-repair [{rep['notes']}] {raw[:40]!r} → {text[:40]!r}",
            flush=True,
        )

    # 0b) Farewell always ends session — never hijack into stock/history tools
    if _is_session_end(text):
        return {
            "target": "respond",
            "mode": "short",
            "reason": "session-end",
            "source": "rules",
            "agent": "",
            "original_text": text,
            "clarify_question": "",
            "raw_text": raw,
            "plan_ms": f"{(time.monotonic() - t0) * 1000:.0f}",
        }

    # 1) Resume pending secondary question (repair applied)
    resolved = session_pending.try_resolve(sid, text)
    if resolved is not None:
        resolved = dict(resolved)
        resolved.setdefault("raw_text", raw)
        resolved["plan_ms"] = f"{(time.monotonic() - t0) * 1000:.0f}"
        return resolved

    # 1b) Multi-turn: prior turns about stock + short "AMD" → Hermes with full task
    hist_stock = session_pending.try_continue_stock_from_history(sid, text)
    if hist_stock is not None:
        hist_stock = dict(hist_stock)
        hist_stock.setdefault("raw_text", raw)
        hist_stock["plan_ms"] = f"{(time.monotonic() - t0) * 1000:.0f}"
        return hist_stock

    # 2) One-shot: agent and/or 提示词+任务 already in this utterance
    oneshot = session_pending.parse_oneshot(text)
    if oneshot:
        out = session_pending.plan_from_oneshot(oneshot)
        out = dict(out)
        # Safety: long markers on original utterance always win for capable workers
        if wants_long_mode(text) and out.get("target") in _LONG_CAPABLE:
            out["mode"] = "long"
        # Hermes stock without symbol → ask once, don't run empty query
        body = str(out.get("original_text") or text)
        if (
            out.get("target") == "hermes"
            and session_pending.needs_stock_slot(body)
        ):
            slot = session_pending.start_stock_slot(
                sid, body, agent=str(out.get("agent") or "hermes")
            )
            slot = dict(slot)
            slot.setdefault("raw_text", raw)
            slot["plan_ms"] = f"{(time.monotonic() - t0) * 1000:.0f}"
            return slot
        # Expand stock oneshot to a clear Hermes task
        if out.get("target") == "hermes" and session_pending.looks_like_stock_query(body):
            sym = session_pending.extract_stock_symbol(body)
            if sym:
                out["original_text"] = session_pending.stock_task_text(sym, extra=body)
        out.setdefault("raw_text", raw)
        out["plan_ms"] = f"{(time.monotonic() - t0) * 1000:.0f}"
        return out

    # 3) Fast classify (rules → optional model ≤1–2s → keyword fallback)
    plan = intent_classifier.classify(text, session_id=sid)
    target = plan.get("target") or "respond"
    mode = plan.get("mode") or "short"
    source = plan.get("source") or ""
    reason = plan.get("reason") or source or "classifier"

    # 4) Coding: only clarify when incomplete (auto mode)
    if target == "hermes" and session_pending.needs_coding_agent_clarify(text):
        out = session_pending.start_coding_clarify(sid, text, mode=mode)
        out = dict(out)
        out["plan_ms"] = f"{(time.monotonic() - t0) * 1000:.0f}"
        return out

    # 4b) Stock without symbol → ask; with symbol → force Hermes task text
    if session_pending.looks_like_stock_query(text) or target == "hermes" and session_pending.looks_like_stock_query(text):
        if session_pending.needs_stock_slot(text):
            out = session_pending.start_stock_slot(sid, text, agent="hermes")
            out = dict(out)
            out["plan_ms"] = f"{(time.monotonic() - t0) * 1000:.0f}"
            return out
        sym = session_pending.extract_stock_symbol(text)
        if sym and HERMES_ROUTE:
            plan_ms = f"{(time.monotonic() - t0) * 1000:.0f}"
            return {
                "target": "hermes",
                "mode": mode if mode in ("short", "long") else "short",
                "reason": reason or "rules:stock",
                "source": source or "rules",
                "agent": "hermes",
                "original_text": session_pending.stock_task_text(sym, extra=text),
                "raw_text": raw,
                "plan_ms": plan_ms,
            }

    # 5) Coding with full task but no agent → already handled by oneshot default hermes
    plan_ms = f"{(time.monotonic() - t0) * 1000:.0f}"
    return {
        "target": target,
        "mode": mode,
        "reason": reason,
        "source": source,
        "agent": "",
        "original_text": text,  # repaired
        "raw_text": raw,
        "plan_ms": plan_ms,
    }


def _plan_node(state: SupervisorState) -> dict:
    text = state.get("text") or ""
    sid = state.get("session_id") or ""
    # Instant overlay feedback before any LLM (rules path is ms)
    ux_bridge.progress("理解指令…", state="thinking", source="plan", priority=96)
    plan = plan_dispatch(text, sid)
    src = plan.get("source") or "?"
    agent = plan.get("agent") or ""
    plan_ms = plan.get("plan_ms") or "?"
    print(
        f"aipc-agent: dispatch target={plan['target']} mode={plan.get('mode')} "
        f"agent={agent or '-'} source={src} plan_ms={plan_ms} ({plan.get('reason')})",
        flush=True,
    )
    if plan.get("target") == "clarify":
        ux_bridge.progress("需要确认…", state="thinking", source="clarify")
    else:
        ux_bridge.announce_plan(
            plan["target"],
            plan.get("mode") or "short",
            agent=agent,
            source=str(src),
        )
    return {
        "target": plan["target"],
        "mode": plan.get("mode") or "short",
        "dispatch_reason": plan.get("reason") or "",
        "agent": agent,
        "original_text": plan.get("original_text") or text,
        "clarify_question": plan.get("clarify_question") or "",
        "force_text": plan.get("force_text") or "",
    }


def _route_after_plan(state: SupervisorState) -> str:
    t = state.get("target") or "respond"
    if t in (
        "respond",
        "daily_assistant",
        "hermes",
        "coder",
        "clarify",
        "job_status",
        "screen_see",
    ):
        return t
    return "respond"


# Back-compat for tests that call _route directly (no plan state yet)
def _route(state: SupervisorState) -> str:
    plan = plan_dispatch(state.get("text") or "", state.get("session_id") or "")
    return plan["target"]


def supervisor():
    graph = StateGraph(SupervisorState)
    graph.add_node("plan", _plan_node)
    graph.add_node("respond", _respond)
    graph.add_node("daily_assistant", _daily_assistant_node)
    graph.add_node("hermes", _hermes_node)
    graph.add_node("coder", _coder_node)
    graph.add_node("clarify", _clarify_node)
    graph.add_node("job_status", _job_status_node)
    graph.add_node("screen_see", _screen_see_node)
    graph.set_entry_point("plan")
    graph.add_conditional_edges(
        "plan",
        _route_after_plan,
        {
            "respond": "respond",
            "daily_assistant": "daily_assistant",
            "hermes": "hermes",
            "coder": "coder",
            "clarify": "clarify",
            "job_status": "job_status",
            "screen_see": "screen_see",
        },
    )
    graph.add_edge("respond", END)
    graph.add_edge("daily_assistant", END)
    graph.add_edge("hermes", END)
    graph.add_edge("coder", END)
    graph.add_edge("clarify", END)
    graph.add_edge("job_status", END)
    graph.add_edge("screen_see", END)
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
    assert _route({"text": "今天有什么会议", "session_id": "s"}) == "daily_assistant"
    assert _route({"text": "搜一下 python", "session_id": "s"}) == "daily_assistant"
    assert _route({"text": "what is the capital of France", "session_id": "s"}) == "respond"
    assert _route({"text": "看一下桌面", "session_id": "voice"}) == "screen_see"
    assert _route({"text": "what's on screen", "session_id": "s"}) == "screen_see"
    assert screen_see.wants_screen_see("看桌面") is True
    # Substring traps must NOT steal ordinary chat (AC2/AC4)
    for ordinary in (
        "what is research",
        "I already told you",
        "my profile",
    ):
        assert wants_daily_assistant(ordinary) is False, ordinary
        assert _route({"text": ordinary, "session_id": "s"}) == "respond", ordinary
    assert wants_daily_assistant("web search for python") is True
    # Ordinary chat must stay on fast supervisor (not Hermes)
    for ordinary in (
        "帮我写一首诗",
        "写一个小故事",
        "帮我做一下总结",
        "帮我解释重力",
        "shell 是什么",
        "打开 terminal",
        "what is shell",
    ):
        assert _route({"text": ordinary, "session_id": "s"}) == "respond", ordinary
        assert wants_hermes(ordinary) is False, ordinary
    # Hermes route only when binary present
    if hermes_bridge.available() and HERMES_ROUTE:
        assert _route({"text": "用hermes帮我写脚本", "session_id": "s"}) == "hermes"
        assert _route({"text": "帮我debug这个bug", "session_id": "s"}) == "hermes"
        assert _route({"text": "写代码实现排序", "session_id": "s"}) == "hermes"
        assert wants_hermes("用hermes帮我写脚本") is True
    hermes_bridge.self_test()

    assert da.calendar_lookup.invoke({"query": "x"})["status"] == "not_configured"
    assert da.email_lookup.invoke({"query": "x"})["status"] == "not_configured"
    denied = da.files_read.invoke({"path": "/etc/passwd"})
    assert denied["status"] in {"not_configured", "denied"}
    assert "root:" not in str(denied)
    if hasattr(da, "usage_lookup"):
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
         patch.object(memory, "internalize") as remember, \
         patch.object(ChatLiteLLM, "invoke", return_value=AIMessage(content="mocked reply")):
        assert graph.invoke({"text": "hello", "session_id": "s1"})["text"] == "mocked reply"
        result = da_graph.invoke({"text": "book a meeting", "session_id": "s2", "messages": []})
        assert result["text"] == "mocked reply"
        # Supervisor respond recalls+remembers; daily_assistant graph does not use mem0.
        assert recall.call_count >= 1
        assert remember.call_count >= 1  # internalize

    print("self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
