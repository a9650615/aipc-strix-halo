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

# Default ON — product: autonomous skill growth is always available.
ENABLED = os.environ.get("AIPC_SKILL_LEARN", "1") not in ("0", "false", "no", "off")
# Learning mentor: ornith-35b (strong local reasoner). Async path — may cold-load.
LEARN_MODEL = os.environ.get("AIPC_SKILL_LEARN_MODEL", "ornith-35b")
# If mentor is cold/unreachable, fall back so the queue still advances.
LEARN_FALLBACK_MODEL = os.environ.get(
    "AIPC_SKILL_LEARN_FALLBACK_MODEL", "assistant-gemma"
)
LEARN_TIMEOUT = float(os.environ.get("AIPC_SKILL_LEARN_TIMEOUT", "120"))
MIN_USER = int(os.environ.get("AIPC_SKILL_LEARN_MIN_USER", "6"))
MIN_REPLY = int(os.environ.get("AIPC_SKILL_LEARN_MIN_REPLY", "40"))
MIN_BODY = int(os.environ.get("AIPC_SKILL_LEARN_MIN_BODY", "80"))

_EXTRACT_SYSTEM = (
    "You extract reusable on-device assistant skills from a successful turn. "
    "The skill is stored as a local folder on this PC (NOT in any git repo). "
    "Focus on the PATH (how to find info next time), not memorizing one answer. "
    "When TOOL_TRAIL is present, prefer those real tools/URLs/query patterns over "
    "guessing from the spoken reply alone. "
    "Return ONLY JSON, no markdown fences:\n"
    '{"learn":true|false,'
    '"title":"short skill title",'
    '"tags":["tag1","tag2"],'
    '"triggers":["phrases that should recall this skill"],'
    '"body":"markdown PROCEDURE: ordered steps, which tools/sites/query patterns, '
    'what fields to extract (title, cast, URL). Do NOT only paste the one-shot answer."}'
    "\nSet learn=false for chit-chat, greetings, pure opinions, or failures. "
    "Set learn=true when the turn shows a reusable lookup/tool procedure "
    "(catalog codes, web research, site navigation) OR TOOL_TRAIL has real URLs/tools. "
    "body must be steps a future agent can follow without already knowing the answer. "
    "Do not moralize. Keep body under 900 Chinese/English characters."
)


def _worth_candidate(
    user: str, reply: str, *, kind: str, trail: str = ""
) -> bool:
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
        "没从网页查到",
        "无法核实",
        "無法核實",
    )
    if any(b in r or b.lower() in r.lower() for b in bad):
        return False
    if kind in ("canned", "clarify"):
        return False
    # greetings
    if re.fullmatch(r"(你好|您好|嗨|hi|hello)[。.!！?？]*", u, re.I):
        return False
    # Do not grow skills from ungrounded invents (esp. respond-path fakes)
    try:
        from aipc_agent.grounding import should_learn

        if not should_learn(u, r, kind=kind, trail=trail):
            print(
                f"aipc-agent: skill-learn reject ungrounded kind={kind} "
                f"trail={bool((trail or '').strip())}",
                flush=True,
            )
            return False
    except Exception:
        pass
    return True


def _parse_json_obj(raw: str) -> dict[str, Any] | None:
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


def _openai_json(user_payload: str, *, model: str) -> dict[str, Any] | None:
    import urllib.request

    base = (os.environ.get("AIPC_LITELLM_URL") or "http://127.0.0.1:4000").rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    # Trail-rich payloads need more room for procedure fidelity.
    cap = 5500 if "TOOL_TRAIL:" in user_payload else 3500
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_payload[:cap]},
        ],
        "max_tokens": 900,
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
        print(f"aipc-agent: skill-learn llm fail model={model}: {exc}", flush=True)
        return None
    try:
        from aipc_agent._util import text_of

        raw = text_of((data.get("choices") or [{}])[0].get("message", {}).get("content"))
    except Exception:
        raw = str((data.get("choices") or [{}])[0].get("message", {}).get("content") or "")
    return _parse_json_obj(raw or "")


def _extract_with_mentor(payload: str) -> dict[str, Any] | None:
    """Ask ornith (LEARN_MODEL) first; on fail / weak skip, seek fallback help.

    Learning path is allowed to cold-load the strong mentor — it is async.
    """
    models: list[str] = []
    for m in (LEARN_MODEL, LEARN_FALLBACK_MODEL):
        m = (m or "").strip()
        if m and m not in models:
            models.append(m)

    best: dict[str, Any] | None = None
    for i, model in enumerate(models):
        obj = _openai_json(payload, model=model)
        if not obj:
            print(
                f"aipc-agent: skill-learn mentor miss model={model} "
                f"({i + 1}/{len(models)})",
                flush=True,
            )
            continue
        if not obj.get("learn"):
            print(
                f"aipc-agent: skill-learn model={model} said learn=false",
                flush=True,
            )
            # Strong mentor said no — trust it; do not demote to weaker "yes"
            if model == LEARN_MODEL or i == 0:
                return None
            continue
        title = str(obj.get("title") or "").strip()
        body = str(obj.get("body") or "").strip()
        if not title or not body:
            continue
        if len(body) < MIN_BODY and i + 1 < len(models):
            print(
                f"aipc-agent: skill-learn thin body model={model} "
                f"chars={len(body)} — seek next mentor",
                flush=True,
            )
            best = obj
            continue
        print(
            f"aipc-agent: skill-learn extract ok model={model} body_chars={len(body)}",
            flush=True,
        )
        return obj
    return best if best and best.get("learn") else None


def _build_learn_payload(
    user: str,
    reply: str,
    *,
    kind: str,
    agent: str,
    trail: str = "",
) -> str:
    parts = [
        f"kind={kind} agent={agent}",
        f"USER:\n{user[:800]}",
        f"ASSISTANT (success):\n{reply[:1200]}",
    ]
    tr = (trail or "").strip()
    if tr:
        parts.append(
            "TOOL_TRAIL (real tools/URLs from this run — prefer these in body):\n"
            f"{tr[:2000]}"
        )
    return "\n\n".join(parts) + "\n"


# Exclude markdown fences/backticks so re-harvest from SKILL.md stays clean
_URL_RE = re.compile(r"https?://[^\s\]\)\"'`<>，。、]+", re.I)


def _urls_from_blob(blob: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer(blob or ""):
        u = m.group(0).rstrip(".,;:)")
        if u in seen:
            continue
        seen.add(u)
        # skip pure store homepages
        if re.fullmatch(
            r"https?://(www\.)?(fanza\.com|dmm\.co\.jp|dmm\.com)/?", u, re.I
        ):
            continue
        out.append(u)
        if len(out) >= 12:
            break
    return out


def _hosts_from_urls(urls: list[str]) -> list[str]:
    hosts: list[str] = []
    for u in urls:
        try:
            from urllib.parse import urlparse

            h = (urlparse(u).hostname or "").lower()
        except Exception:
            h = ""
        if h and h not in hosts:
            hosts.append(h)
    return hosts[:12]


def _prior_web_lookup_skill() -> dict[str, Any] | None:
    """Load existing web-lookup-path skill if present (for host accumulation)."""
    try:
        for sk in skill_store.list_skills():
            if str(sk.get("id") or "") == "web-lookup-path":
                return sk
    except Exception:
        pass
    return None


def _merge_unique(seq: list[str], extra: list[str], *, cap: int = 24) -> list[str]:
    out: list[str] = []
    for x in list(seq) + list(extra):
        x = (x or "").strip()
        if x and x not in out:
            out.append(x)
        if len(out) >= cap:
            break
    return out


def path_skill_from_evidence(
    user: str,
    reply: str,
    *,
    trail: str = "",
) -> dict[str, Any] | None:
    """Deterministic PATH skill from real URLs (no mentor / no supervisor answers).

    Side-path hosts she discovers herself are merged into the local skill tree
    so the next similar turn prefers those hosts. Process code never hardcodes
    catalog sites — only harvests what this machine's tools actually opened.
    """
    urls = _urls_from_blob(f"{trail or ''}\n{reply or ''}")
    if not urls:
        return None
    hosts = _hosts_from_urls(urls)
    # Accumulate side paths from prior successful learns on this machine
    prior = _prior_web_lookup_skill()
    prior_body = skill_store.read_skill_body(prior) if prior else ""
    prior_urls = _urls_from_blob(prior_body)
    prior_hosts = _hosts_from_urls(prior_urls)
    # also lines like `- `host.example``
    for m in re.finditer(r"`([a-z0-9.-]+\.[a-z]{2,})`", prior_body, re.I):
        h = m.group(1).lower()
        if h not in prior_hosts:
            prior_hosts.append(h)
    hosts = _merge_unique(hosts, prior_hosts, cap=16)
    urls = _merge_unique(urls, prior_urls, cap=16)

    codes: list[str] = []
    try:
        from aipc_agent.grounding import extract_product_codes

        codes = extract_product_codes(user)
    except Exception:
        codes = []
    steps = [
        "## Procedure learned on this machine (accumulated tool successes)",
        "",
        "Side paths are allowed: any host that once returned real page evidence",
        "is kept here. Prefer these before random cold starts. Do not invent facts.",
        "",
        "1. Identify the lookup key in the user request (code, name, id, …).",
        "2. Search with tools/engines (web_search and/or browser search engines).",
        "3. Prefer hosts already proven on this machine (skill tree accumulation):",
    ]
    for h in hosts:
        steps.append(f"   - `{h}`")
    steps.append("4. URL patterns observed on successful runs (keys generalized):")
    for u in urls[:10]:
        u_pat = u
        for c in codes:
            u_pat = re.sub(re.escape(c), "{KEY}", u_pat, flags=re.I)
            u_pat = re.sub(
                re.escape(c.replace("-", "")), "{KEY}", u_pat, flags=re.I
            )
        steps.append(f"   - `{u_pat[:220]}`")
    steps.extend(
        [
            "5. Open pages with browser tools; extract only fields present on the page.",
            "6. If a host fails (403/captcha), try the next proven host or another engine.",
            "7. Reply with facts + at least one concrete item URL from tools.",
            "8. On success, path-harvest merges new hosts into this skill (self-grow).",
        ]
    )
    body = "\n".join(steps)
    title = "web-lookup-path"
    tags = ["lookup", "web", "tools", "sidepath-learned", *hosts[:8]]
    if codes:
        tags.append("product-code")
    # Triggers: codes + tokens from this user turn only
    triggers: list[str] = list(codes[:6])
    for tok in re.findall(r"[\w\u4e00-\u9fff]{2,}", user or ""):
        if tok not in triggers and len(triggers) < 12:
            triggers.append(tok[:40])
    if prior:
        for t in prior.get("triggers") or []:
            t = str(t)[:80]
            if t and t not in triggers and len(triggers) < 16:
                triggers.append(t)
    return {
        "learn": True,
        "title": title,
        "tags": tags,
        "triggers": triggers,
        "body": body,
        "skill_id": "web-lookup-path",
        "source": "path-harvest",
    }


def _merge_path_bodies(base: str, mentor_body: str) -> str:
    """Keep harvested hosts/URLs; append mentor steps if they add procedure."""
    base = (base or "").strip()
    mentor_body = (mentor_body or "").strip()
    if not mentor_body:
        return base
    if not base:
        return mentor_body
    if len(mentor_body) < 40:
        return base
    # Avoid duplicating huge mentor paste of the one-shot answer
    if mentor_body in base:
        return base
    return (
        base
        + "\n\n## Mentor notes (procedure only)\n"
        + mentor_body[:700]
    )


def _learn_sync(
    user: str,
    reply: str,
    *,
    session_id: str,
    kind: str,
    agent: str,
    trail: str = "",
) -> dict[str, Any] | None:
    if not ENABLED:
        return None
    if not _worth_candidate(user, reply, kind=kind, trail=trail):
        return None
    if trail:
        print(
            f"aipc-agent: skill-learn with trail_chars={len(trail.strip())}",
            flush=True,
        )

    # 1) Deterministic harvest from real URLs (future turns skip dead ends)
    harvested = path_skill_from_evidence(user, reply, trail=trail)

    # 2) Optional mentor polish (async path; may fail if GPU cold)
    payload = _build_learn_payload(
        user, reply, kind=kind, agent=agent, trail=trail
    )
    mentor = _extract_with_mentor(payload)

    if harvested:
        title = str(harvested.get("title") or "web-lookup-path")
        body = str(harvested.get("body") or "")
        tags = list(harvested.get("tags") or [])
        triggers = list(harvested.get("triggers") or [])
        skill_id = str(harvested.get("skill_id") or "web-lookup-path")
        source = f"aipc-learn:{kind}:path-harvest"
        if mentor and mentor.get("learn"):
            body = _merge_path_bodies(body, str(mentor.get("body") or ""))
            tags = list(
                dict.fromkeys(
                    tags + [str(t)[:40] for t in (mentor.get("tags") or []) if t]
                )
            )[:16]
            triggers = list(
                dict.fromkeys(
                    triggers
                    + [str(t)[:80] for t in (mentor.get("triggers") or []) if t]
                )
            )[:16]
            source = f"aipc-learn:{kind}:path+mentor"
            print("aipc-agent: skill-learn path-harvest + mentor merge", flush=True)
        else:
            print("aipc-agent: skill-learn path-harvest only (mentor skip/fail)", flush=True)
    elif mentor and mentor.get("learn"):
        title = str(mentor.get("title") or "").strip()
        body = str(mentor.get("body") or "").strip()
        tags = [str(t)[:40] for t in (mentor.get("tags") or []) if t][:12]
        triggers = [str(t)[:80] for t in (mentor.get("triggers") or []) if t][:12]
        skill_id = None
        source = f"aipc-learn:{kind}"
    else:
        print("aipc-agent: skill-learn nothing to save", flush=True)
        return None

    if not title or not body or len(body) < 40:
        return None
    examples = [user.strip()[:200]]
    meta = skill_store.save_skill(
        title=title,
        body=body,
        tags=tags,
        triggers=triggers,
        examples=examples,
        source=source,
        session_id=session_id,
        skill_id=skill_id,
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
                    "learn_model": LEARN_MODEL,
                    "had_trail": bool((trail or "").strip()),
                    "source": source,
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
    trail: str = "",
) -> None:
    """Enqueue skill extraction on the background learn worker (non-blocking).

    Prefer the shared learn_queue so TTS/voice return is never waiting on LLM
    skill extract. Falls back to a daemon thread if the queue is unavailable.
    Optional trail = Hermes tool/URL footprint from the same run.
    """
    if not ENABLED:
        return
    if not _worth_candidate(user, reply, kind=kind, trail=trail):
        return
    try:
        from aipc_agent.learn_queue import enqueue_skill_extract

        if enqueue_skill_extract(
            user,
            reply,
            session_id=session_id,
            kind=kind,
            agent=agent,
            trail=trail,
        ):
            return
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: learn_queue enqueue fail: {exc}", flush=True)

    def _run() -> None:
        try:
            _learn_sync(
                user,
                reply,
                session_id=session_id,
                kind=kind,
                agent=agent,
                trail=trail,
            )
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
