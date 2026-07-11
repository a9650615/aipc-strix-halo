"""Streaming chat path for voice turns (openspec: voice-streaming-turn).

SSE event schema (each `data: <json>` line):

  {"event":"session_id","session_id":"...","task_id":"..."}
  {"event":"token","text":"<delta>"}
  {"event":"done","text":"<full reply>","task_id":"..."}
  {"event":"error","message":"...","code":"upstream_error"}

Voice stream path (S2): no tools, mem0 recall pre-stream + remember post-stream.
Tool routes (daily_assistant / hermes) fall back to a single full reply as one
token so clients keep one client code path. Non-stream POST /chat is unchanged.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from aipc_agent import hermes_bridge, memory
from aipc_agent.daily_assistant import daily_assistant
from aipc_agent.graphs import (
    HERMES_SKIP_REMEMBER,
    LITELLM_BASE_URL,
    SUPERVISOR_MODEL,
    SUPERVISOR_SYSTEM_PROMPT,
    VOICE_SYSTEM_PROMPT_EXTRA,
    _is_voice_session,
    _route,
)

# Re-export schema comment for grep / docs (task 1.1 freeze).
SSE_EVENTS = ("session_id", "token", "done", "error")

_daily_graph = None


def _get_daily():
    global _daily_graph
    if _daily_graph is None:
        _daily_graph = daily_assistant()
    return _daily_graph


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _messages_for_voice(text: str, session_id: str) -> list[dict[str, str]]:
    system = SUPERVISOR_SYSTEM_PROMPT
    if _is_voice_session(session_id):
        system = SUPERVISOR_SYSTEM_PROMPT + " " + VOICE_SYSTEM_PROMPT_EXTRA
    remembered = memory.recall(text, session_id, agent=memory.AGENT_CHAT)
    # Single leading system (Qwen chat templates reject multi-system)
    if remembered:
        system = system + f"\n\nRelevant remembered facts:\n{remembered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


def _max_tokens(session_id: str) -> int:
    # Do not cap worker output for TTS length — spoken_summary is separate.
    voice = _is_voice_session(session_id)
    if voice:
        return 256 if SUPERVISOR_MODEL == "resident-small" else 512
    return 512 if SUPERVISOR_MODEL == "resident-small" else 2048


def _litellm_stream(
    text: str,
    session_id: str,
    *,
    opener=urllib_request.urlopen,
) -> Iterator[str]:
    """Yield token deltas from LiteLLM OpenAI-compatible stream."""
    body = json.dumps(
        {
            "model": SUPERVISOR_MODEL,
            "messages": _messages_for_voice(text, session_id),
            "stream": True,
            "max_tokens": _max_tokens(session_id),
        }
    ).encode("utf-8")
    req = urllib_request.Request(
        f"{LITELLM_BASE_URL}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer aipc-local",
        },
        method="POST",
    )
    timeout = float(os.environ.get("AIPC_STREAM_LLM_TIMEOUT", "120"))
    with opener(req, timeout=timeout) as resp:
        while True:
            raw = resp.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                yield str(piece)


def _batch_reply(text: str, session_id: str) -> str:
    """Non-stream path for tool routes (daily_assistant / hermes)."""
    route = _route({"text": text, "session_id": session_id})
    if route == "hermes":
        result = hermes_bridge.run(text, session_id)
        return str(result.get("text") or "").strip() or "Hermes 没有返回内容。"
    if route == "daily_assistant":
        result = _get_daily().invoke(
            {"text": text, "session_id": session_id, "messages": []}
        )
        return str(result.get("text") or "").strip()
    # Should not land here often — stream path handles "respond".
    from aipc_agent.graphs import supervisor

    out = supervisor().invoke({"text": text, "session_id": session_id})
    return str(out.get("text") or "").strip()


def iter_chat_sse(
    text: str,
    session_id: str | None = None,
    *,
    opener=urllib_request.urlopen,
) -> Iterator[str]:
    """Yield SSE frames for one chat turn."""
    task_id = str(uuid.uuid4())
    sid = session_id or task_id
    yield _sse({"event": "session_id", "session_id": sid, "task_id": task_id})

    if not (text or "").strip():
        msg = "没听清楚，请再说一次。" if _is_voice_session(sid) else "empty text"
        yield _sse({"event": "error", "message": msg, "code": "empty_text"})
        return

    route = _route({"text": text, "session_id": sid})
    full_parts: list[str] = []

    try:
        if route != "respond":
            # Tools / Hermes: one shot, still SSE-shaped.
            reply = _batch_reply(text, sid)
            full_parts.append(reply)
            if reply:
                yield _sse({"event": "token", "text": reply})
        else:
            for piece in _litellm_stream(text, sid, opener=opener):
                full_parts.append(piece)
                yield _sse({"event": "token", "text": piece})
    except Exception as exc:  # noqa: BLE001 — surface as SSE error for voice client
        yield _sse(
            {
                "event": "error",
                "message": str(exc),
                "code": "upstream_error",
            }
        )
        return

    full = "".join(full_parts).strip()
    # mem0: skip noisy hermes transcripts when configured (same as graphs._hermes_node).
    if full and not (
        route == "hermes" and HERMES_SKIP_REMEMBER
    ):
        try:
                        memory.internalize(
                text,
                full,
                sid,
                agent=memory.AGENT_CHAT if route == "respond" else memory.agent_lane(route),
                kind="stream",
            )
        except Exception:
            pass

    yield _sse({"event": "done", "text": full, "task_id": task_id})


def parse_sse_line(line: str) -> dict[str, Any] | None:
    """Parse one `data: {...}` line into a dict; None if not an event."""
    s = (line or "").strip()
    if not s.startswith("data:"):
        return None
    payload = s[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def self_test() -> None:
    """Offline: schema helpers + mocked stream; no network."""
    from io import BytesIO
    from unittest.mock import patch

    assert set(SSE_EVENTS) == {"session_id", "token", "done", "error"}
    frame = _sse({"event": "token", "text": "hi"})
    assert frame.startswith("data: ")
    assert parse_sse_line(frame.strip())["event"] == "token"
    assert parse_sse_line("not-data") is None
    assert parse_sse_line("data: [DONE]") is None

    # Mock LiteLLM SSE body (ASCII-only bytes for py3.14+ strictness)
    fake = (
        b'data: {"choices":[{"delta":{"content":"ni"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"hao"}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    class _Resp(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _opener(req, timeout=None):  # noqa: ARG001
        return _Resp(fake)

    with patch.object(memory, "recall", return_value=""), patch.object(
        memory, "remember", return_value=None
    ):
        events = []
        for frame in iter_chat_sse("你好", "voice-test", opener=_opener):
            ev = parse_sse_line(frame.strip())
            if ev:
                events.append(ev)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "session_id"
    assert "token" in kinds
    assert kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["event"] == "token") == "nihao"
    assert events[-1]["text"] == "nihao"

    # empty text → error
    with patch.object(memory, "recall", return_value=""):
        evs = [
            parse_sse_line(f.strip())
            for f in iter_chat_sse("  ", "voice-test")
            if parse_sse_line(f.strip())
        ]
    assert any(e and e.get("event") == "error" for e in evs)

    assert _route({"text": "what is 2+2", "session_id": "s"}) == "respond"
    print("stream_chat self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit("usage: python -m aipc_agent.stream_chat --self-test")
