"""Best-effort mem0 HTTP client with **per-agent isolation**.

user_id  = human owner (birdyo)
agent_id = which assistant lane wrote/read the memory

Lanes (do not mix for tools):
  chat     — supervisor small-talk / respond / voice defaults
  daily    — calendar / search / usage tool agent
  hermes   — Hermes CLI tool agent
  coder    — coder-agentic / coder-cloud coding models
  screen   — screen-see VLM
  jobs     — background long-task outcomes

Continuous internalization (user 2026-07-10):
  Every successful turn should call internalize() so mem0 *infers* durable
  facts (not only raw transcripts). Voice recall reads the chat lane.
  Fail-soft and async so TTS path is never blocked.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import threading
import time
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("AIPC_MEM0_ENDPOINT", "http://127.0.0.1:7000").rstrip("/")
TIMEOUT = float(os.environ.get("AIPC_MEM0_TIMEOUT", "20.0"))
VOICE_TIMEOUT = float(os.environ.get("AIPC_MEM0_VOICE_TIMEOUT", "1.5"))
# infer=True needs local LLM extraction — do NOT use the 1.5s voice search wall
INFER_TIMEOUT = float(os.environ.get("AIPC_MEM0_INFER_TIMEOUT", "90.0"))
VOICE_MEM0 = os.environ.get("AIPC_VOICE_MEM0", "1") not in ("0", "false", "no")
# Continuous internalization master switch
INTERNALIZE = os.environ.get("AIPC_MEM0_INTERNALIZE", "1") not in ("0", "false", "no")
# Also mirror tool-agent facts into chat lane so voice can recall them
MIRROR_TO_CHAT = os.environ.get("AIPC_MEM0_MIRROR_CHAT", "1") not in ("0", "false", "no")

AGENT_CHAT = "chat"
AGENT_DAILY = "daily"
AGENT_HERMES = "hermes"
AGENT_CODER = "coder"
AGENT_SCREEN = "screen"
AGENT_JOBS = "jobs"

_CODER_MODELS = frozenset(
    {"coder-agentic", "coder-cloud", "ornith-35b", "qwythos-9b", "coder"}
)

# How often to re-consolidate short-term history into mem0 (turn count per session)
_CONSOLIDATE_EVERY = int(os.environ.get("AIPC_MEM0_CONSOLIDATE_EVERY", "4"))
_consol_counts: dict[str, int] = {}
_consol_lock = threading.Lock()


def agent_lane(name: str | None) -> str:
    """Normalize free-form agent/model name to a memory lane."""
    n = (name or "").strip().lower() or AGENT_CHAT
    if n in (AGENT_CHAT, "supervisor", "respond", "resident-small"):
        return AGENT_CHAT
    if n in (AGENT_DAILY, "daily_assistant", "daily-assistant", "tools"):
        return AGENT_DAILY
    if n in (AGENT_HERMES, "hermes_bridge"):
        return AGENT_HERMES
    if n in _CODER_MODELS or n.startswith("coder"):
        return AGENT_CODER
    if n in (AGENT_SCREEN, "screen_see", "screen-see", "vlm"):
        return AGENT_SCREEN
    if n in (AGENT_JOBS, "task_jobs", "long-task"):
        return AGENT_JOBS
    return n.replace(" ", "-")[:40]


def _primary_user() -> str:
    try:
        uids = [int(d) for d in os.listdir("/run/user") if d.isdigit() and int(d) >= 1000]
        if uids:
            return pwd.getpwuid(min(uids)).pw_name
    except (OSError, KeyError, ValueError):
        pass
    return ""


def _user_id(session_id: str) -> str:
    return (
        os.environ.get("AIPC_MEMORY_USER_ID")
        or os.environ.get("AIPC_PRIMARY_USER")
        or _primary_user()
        or os.environ.get("USER")
        or f"session:{session_id}"
    )


def _is_voice_session(session_id: str) -> bool:
    s = (session_id or "").lower()
    return any(k in s for k in ("voice", "wake", "ptt", "aipc-voice"))


def _post(path: str, payload: dict, *, timeout: float | None = None) -> object | None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        ENDPOINT + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    wall = TIMEOUT if timeout is None else timeout
    try:
        with urllib.request.urlopen(req, timeout=wall) as resp:
            return json.loads(resp.read() or b"null")
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError):
        return None


def _format_memories(data: object) -> str:
    if isinstance(data, dict):
        items = data.get("results") or data.get("memories") or data.get("data") or []
    else:
        items = data if isinstance(data, list) else []
    lines = []
    for item in items[:5]:
        if isinstance(item, str):
            lines.append(item)
        elif isinstance(item, dict):
            text = item.get("memory") or item.get("text") or item.get("content")
            if text:
                lines.append(str(text))
    return "\n".join(lines)


def recall(
    query: str,
    session_id: str,
    limit: int = 5,
    *,
    agent: str = AGENT_CHAT,
) -> str:
    """Recall memories for one agent lane only (never cross daily↔coder)."""
    if _is_voice_session(session_id) and not VOICE_MEM0:
        return ""
    lane = agent_lane(agent)
    payload = {
        "query": query,
        "user_id": _user_id(session_id),
        "agent_id": lane,
        "limit": limit,
    }
    wall = VOICE_TIMEOUT if _is_voice_session(session_id) else TIMEOUT
    for path in ("/search", "/memories/search"):
        text = _format_memories(_post(path, payload, timeout=wall))
        if text:
            return text
    # Voice: also try chat lane when primary empty (internalized tool facts live there)
    if lane != AGENT_CHAT and _is_voice_session(session_id):
        payload["agent_id"] = AGENT_CHAT
        for path in ("/search", "/memories/search"):
            text = _format_memories(_post(path, payload, timeout=wall))
            if text:
                return text
    return ""


def remember(
    text: str,
    session_id: str,
    *,
    infer: bool = False,
    agent: str = AGENT_CHAT,
    timeout: float | None = None,
    async_: bool | None = None,
) -> None:
    """Store memory under agent_id lane.

    infer=True → mem0 uses local LLM to extract durable facts (internalization).
    Voice search stays fast; infer writes use a longer wall and are always async.
    """
    if _is_voice_session(session_id) and not VOICE_MEM0:
        return
    lane = agent_lane(agent)
    body = (text or "").strip()
    if not body:
        return

    if timeout is None:
        if infer:
            timeout = INFER_TIMEOUT
        elif _is_voice_session(session_id):
            timeout = VOICE_TIMEOUT
        else:
            timeout = TIMEOUT

    def _do() -> None:
        payload = {
            "messages": [{"role": "user", "content": body[:4000]}],
            "user_id": _user_id(session_id),
            "agent_id": lane,
            "metadata": {
                "source": "aipc-agent-orchestrator",
                "session_id": session_id,
                "agent": lane,
                "infer": bool(infer),
                "ts": time.time(),
            },
            "infer": bool(infer),
        }
        ok = _post("/memories", payload, timeout=timeout)
        if ok is None:
            _post("/memory", payload, timeout=timeout)
        else:
            print(
                f"aipc-agent: mem0 {'infer' if infer else 'store'} ok lane={lane} "
                f"chars={len(body)}",
                flush=True,
            )

    # Infer and voice always async so chat/TTS never block
    run_async = async_
    if run_async is None:
        run_async = (
            infer
            or _is_voice_session(session_id)
            or os.environ.get("AIPC_MEM0_ASYNC", "1") not in ("0", "false", "no")
        )
    if run_async:
        threading.Thread(
            target=_do, name=f"mem0-{'infer' if infer else 'store'}-{lane}", daemon=True
        ).start()
        return
    _do()


def _worth_internalizing(user_text: str, assistant_text: str) -> bool:
    """Skip pure noise / errors / empty so mem0 is not filled with junk."""
    u = re.sub(r"[\s。.!！?？,，、~～]+", "", (user_text or "").lower())
    a = (assistant_text or "").strip()
    if len(u) < 2 and len(a) < 4:
        return False
    junk_a = (
        "没听清楚",
        "沒聽清楚",
        "本地模型调用失败",
        "本地模型這會兒",
        "处理超时",
        "處理超時",
        "搜索：error",
        "searxng unreachable",
    )
    if any(j in a for j in junk_a):
        return False
    greets = {"你好", "您好", "嗨", "hello", "hi", "谢谢", "謝謝", "再见", "再見", "bye"}
    if u in greets and len(a) < 40:
        return False
    return True


def internalize(
    user_text: str,
    assistant_text: str,
    session_id: str,
    *,
    agent: str = AGENT_CHAT,
    kind: str = "turn",
) -> None:
    """Continuous internalization: extract durable facts into mem0 (async).

    Always infer=True. Mirrors tool-lane outcomes into chat so voice recall works.
    """
    if not INTERNALIZE:
        return
    if _is_voice_session(session_id) and not VOICE_MEM0:
        return
    if not _worth_internalizing(user_text, assistant_text):
        return

    lane = agent_lane(agent)
    blob = (
        f"[{kind}] User: {(user_text or '').strip()[:800]}\n"
        f"Assistant: {(assistant_text or '').strip()[:1200]}"
    )
    remember(blob, session_id, infer=True, agent=lane, timeout=INFER_TIMEOUT)

    if MIRROR_TO_CHAT and lane != AGENT_CHAT:
        remember(
            f"[internalized from {lane}] " + blob,
            session_id,
            infer=True,
            agent=AGENT_CHAT,
            timeout=INFER_TIMEOUT,
        )

    # Periodic consolidation of short-term buffer → long-term facts
    try:
        consolidate_if_due(session_id, agent=AGENT_CHAT)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: consolidate skip: {exc}", flush=True)


def consolidate_if_due(session_id: str, *, agent: str = AGENT_CHAT) -> None:
    """Every N turns, re-internalize recent dialogue as a structured memory pass."""
    if not INTERNALIZE or _CONSOLIDATE_EVERY <= 0:
        return
    sid = (session_id or "default").strip()
    with _consol_lock:
        n = _consol_counts.get(sid, 0) + 1
        _consol_counts[sid] = n
        if n % _CONSOLIDATE_EVERY != 0:
            return
    consolidate_session(sid, agent=agent, reason=f"every-{_CONSOLIDATE_EVERY}")


def consolidate_session(
    session_id: str,
    *,
    agent: str = AGENT_CHAT,
    reason: str = "session-end",
) -> None:
    """Dump short-term dialogue into mem0 with infer=True (async)."""
    if not INTERNALIZE:
        return
    try:
        from aipc_agent import agent_context
    except Exception:
        return
    hist = agent_context.format_history(session_id, agent)
    if not hist or len(hist) < 8:
        # also try chat lane history for voice
        hist = agent_context.format_history(session_id, AGENT_CHAT)
    if not hist or len(hist) < 8:
        return
    body = (
        f"[consolidate:{reason}] Recent dialogue — extract durable user preferences, "
        f"names, ongoing tasks, and tool outcomes as facts:\n{hist[:3500]}"
    )
    remember(body, session_id, infer=True, agent=AGENT_CHAT, timeout=INFER_TIMEOUT)
    print(
        f"aipc-agent: mem0 consolidate queued sid={session_id!r} reason={reason}",
        flush=True,
    )


def self_test() -> None:
    global ENDPOINT
    assert agent_lane("coder-agentic") == AGENT_CODER
    assert agent_lane("daily_assistant") == AGENT_DAILY
    assert agent_lane("hermes") == AGENT_HERMES
    assert agent_lane("coder-agentic") != agent_lane("daily")
    assert _format_memories({"results": [{"memory": "likes concise replies"}]}) == (
        "likes concise replies"
    )
    assert _worth_internalizing("我叫小明", "好的小明") is True
    assert _worth_internalizing("你好", "你好") is False
    old_endpoint = ENDPOINT
    ENDPOINT = "http://127.0.0.1:9"
    assert recall("x", "s", agent=AGENT_DAILY) == ""
    remember("hello", "s", agent=AGENT_CODER)
    internalize("记着我喜欢简洁", "好的", "s", agent=AGENT_CHAT)
    ENDPOINT = old_endpoint
    print("memory self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
