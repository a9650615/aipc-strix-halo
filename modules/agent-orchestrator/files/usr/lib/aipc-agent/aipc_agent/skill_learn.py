"""Need-triggered skill growth process (on-box only).

After a successful tool/worker turn, optionally ask a local LLM whether a
reusable procedure was demonstrated; if yes, write a modular skill under
the local skill root (never into aipc modules/).

Learning is async relative to TTS / reply return.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from aipc_agent import skill_store

ENABLED = os.environ.get("AIPC_SKILL_LEARN", "1") not in ("0", "false", "no", "off")
LEARN_MODEL = os.environ.get("AIPC_SKILL_LEARN_MODEL", "assistant-gemma")
LEARN_TIMEOUT = float(os.environ.get("AIPC_SKILL_LEARN_TIMEOUT", "45"))
MIN_USER = int(os.environ.get("AIPC_SKILL_LEARN_MIN_USER", "6"))
MIN_REPLY = int(os.environ.get("AIPC_SKILL_LEARN_MIN_REPLY", "40"))

_EXTRACT_SYSTEM = (
    "You extract reusable on-device assistant skills from a successful turn. "
    "The skill will be stored as a local folder on this PC (not in any git repo). "
    "Return ONLY JSON, no markdown fences:\n"
    '{"learn":true|false,'
    '"title":"short skill title",'
    '"tags":["tag1","tag2"],'
    '"triggers":["phrases that should recall this skill"],'
    '"body":"markdown procedure: how to find/do this next time (steps, sites, queries)"}'
    "\nSet learn=false for chit-chat, pure greetings, one-off opinions, or failures. "
    "Set learn=true when the turn shows a reusable info-lookup or tool procedure "
    "(e.g. how to resolve a catalog/product/media code, how to search a site class). "
    "body must be concrete steps (search queries, site types, what to extract). "
    "Do not moralize. Keep body under 800 Chinese/English characters."
)


def _worth_candidate(user: str, reply: str, *, kind: str) -> bool:
    u = (user or "").strip()
    r = (reply or "").strip()
    if len(u) < MIN_USER or len(r) < MIN_REPLY:
        return False
    # skip obvious fail / empty / policy walls
    bad = (
        "没有返回",
        "连不上",
        "暂时无法",
        "No reply",
        "no reply",
        "处理超时",
        "API call failed",
        "本地模型调用失败",
        "Response truncated",
        "output length limit",
        "empty content",
        "没查到可用结果",
        "任务跑完了，但没有可读",
    )
    if any(b in r or b.lower() in r.lower() for b in bad):
        return False
    if kind in ("canned", "clarify"):
        return False
    # greetings
    if re.fullmatch(r"(你好|您好|嗨|hi|hello)[。.!！?？]*", u, re.I):
        return False
    return True


def _openai_json(user_payload: str) -> dict[str, Any] | None:
    import urllib.request

    base = (os.environ.get("AIPC_LITELLM_URL") or "http://127.0.0.1:4000").rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    body = {
        "model": LEARN_MODEL,
        "messages": [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_payload[:3500]},
        ],
        "max_tokens": 700,
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer aipc-local",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=LEARN_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: skill-learn llm fail: {exc}", flush=True)
        return None
    try:
        from aipc_agent._util import text_of

        raw = text_of((data.get("choices") or [{}])[0].get("message", {}).get("content"))
    except Exception:
        raw = str((data.get("choices") or [{}])[0].get("message", {}).get("content") or "")
    raw = (raw or "").strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _learn_sync(
    user: str,
    reply: str,
    *,
    session_id: str,
    kind: str,
    agent: str,
) -> dict[str, Any] | None:
    if not ENABLED:
        return None
    if not _worth_candidate(user, reply, kind=kind):
        return None
    payload = (
        f"kind={kind} agent={agent}\n"
        f"USER:\n{user[:800]}\n\n"
        f"ASSISTANT (success):\n{reply[:1200]}\n"
    )
    obj = _openai_json(payload)
    if not obj or not obj.get("learn"):
        return None
    title = str(obj.get("title") or "").strip()
    body = str(obj.get("body") or "").strip()
    if not title or not body:
        return None
    tags = [str(t)[:40] for t in (obj.get("tags") or []) if t][:12]
    triggers = [str(t)[:80] for t in (obj.get("triggers") or []) if t][:12]
    # Always keep the original user utterance as an example trigger
    examples = [user.strip()[:200]]
    meta = skill_store.save_skill(
        title=title,
        body=body,
        tags=tags,
        triggers=triggers,
        examples=examples,
        source=f"aipc-learn:{kind}",
        session_id=session_id,
    )
    if meta:
        try:
            from aipc_agent import episode_log

            episode_log.append(
                {
                    "kind": "skill_learned",
                    "session_id": session_id,
                    "skill_id": meta.get("id"),
                    "title": meta.get("title"),
                    "path": meta.get("path"),
                    "from_user": user[:160],
                }
            )
        except Exception:
            pass
    return meta


def maybe_learn_async(
    user: str,
    reply: str,
    *,
    session_id: str = "",
    kind: str = "hermes",
    agent: str = "hermes",
) -> None:
    """Enqueue skill extraction on the background learn worker (non-blocking).

    Prefer the shared learn_queue so TTS/voice return is never waiting on LLM
    skill extract. Falls back to a daemon thread if the queue is unavailable.
    """
    if not ENABLED:
        return
    if not _worth_candidate(user, reply, kind=kind):
        return
    try:
        from aipc_agent.learn_queue import enqueue_skill_extract

        if enqueue_skill_extract(
            user, reply, session_id=session_id, kind=kind, agent=agent
        ):
            return
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: learn_queue enqueue fail: {exc}", flush=True)

    def _run() -> None:
        try:
            _learn_sync(user, reply, session_id=session_id, kind=kind, agent=agent)
        except Exception as exc:  # noqa: BLE001
            print(f"aipc-agent: skill-learn error: {exc}", flush=True)

    threading.Thread(target=_run, name="aipc-skill-learn", daemon=True).start()


def skills_for_query(query: str, *, limit: int = 2) -> str:
    """Prompt block of matching local skills (empty if none)."""
    try:
        hits = skill_store.match(query, limit=limit)
        return skill_store.format_for_prompt(hits)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: skill match fail: {exc}", flush=True)
        return ""
