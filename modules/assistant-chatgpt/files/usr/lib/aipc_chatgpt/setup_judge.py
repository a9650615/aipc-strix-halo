"""Config + optional local LLM to decide setup next steps across sites."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from aipc_chatgpt.engine import WebEngine
from aipc_chatgpt.sites import registry as site_registry


def collect_facts(site_id: str | None = None) -> dict[str, Any]:
    """Gather setup facts **without** launching a browser window.

    Do not call auth_status() here — that opens Chromium and steals focus.
    Infer login from storage_state / profile presence only.
    """
    from aipc_chatgpt.paths import profile_dir, storage_state_path

    cfg = site_registry.load_sites_config()
    sid = site_id or site_registry.default_site_id(cfg)
    sc = site_registry.get_site_config(sid, cfg)
    try:
        import playwright  # noqa: F401

        pw_ok = True
    except ImportError:
        pw_ok = False
    st_path = storage_state_path(sid)
    prof = profile_dir(sid)
    # Heuristic only — full login check needs headless probe if explicitly asked
    logged_guess = None
    if st_path.is_file() and st_path.stat().st_size > 50:
        logged_guess = True  # had a prior export
    elif prof.is_dir() and any(prof.iterdir()):
        logged_guess = None  # profile exists but unknown
    else:
        logged_guess = False
    facts = {
        "site_id": sid,
        "site_title": sc.get("title") or sid,
        "playwright": pw_ok,
        "profile": str(prof),
        "storage_state_present": st_path.is_file(),
        "enabled_sites": site_registry.list_site_ids(cfg),
        "setup_hints": sc.get("setup_hints") or [],
        "logged_in": logged_guess,
        "headless_default": True,
    }
    return facts


def rule_next_steps(facts: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    if not facts.get("playwright"):
        steps.append("install_playwright")
    if facts.get("logged_in") is not True and not facts.get("storage_state_present"):
        steps.append("auth_login")
    elif facts.get("logged_in") is not True:
        steps.append("auth_login_or_import")
    if not steps:
        steps.append("ready")
    return steps


def llm_judge(facts: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    cfg = cfg or site_registry.load_sites_config()
    setup = cfg.get("setup") or {}
    if not setup.get("use_llm", True):
        return None
    model = str(setup.get("model") or "resident-small")
    base = str(setup.get("litellm_base") or "http://127.0.0.1:4000/v1").rstrip("/")
    system = (
        "You plan first-run setup for a multi-site browser assistant. "
        "Reply JSON only: "
        '{"steps":["install_playwright"|"auth_login"|"auth_login_or_import"|"ready",...],'
        '"message_zh":"short user-facing guidance","site_id":"..."}. '
        "Prefer minimal steps. NEVER ask the user to type passwords into the CLI; "
        "login is always in the browser window; we only save session cookies."
    )
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": 200,
        }
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        content = str(content).strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:].strip()
        return json.loads(content)
    except Exception:
        return None


def plan_setup(site_id: str | None = None) -> dict[str, Any]:
    facts = collect_facts(site_id)
    steps = rule_next_steps(facts)
    judged = llm_judge(facts)
    if judged and isinstance(judged.get("steps"), list) and judged["steps"]:
        msg = str(judged.get("message_zh") or "")
        # Rules own hard prerequisites; LLM only enriches copy / optional order
        llm_steps = [str(s) for s in judged["steps"]]
        if facts.get("playwright"):
            llm_steps = [s for s in llm_steps if s != "install_playwright"]
        if not facts.get("playwright") and "install_playwright" not in llm_steps:
            llm_steps = ["install_playwright"] + llm_steps
        # Prefer rule steps when non-empty (authoritative)
        final = steps if steps else llm_steps
        if facts.get("playwright"):
            final = [s for s in final if s != "install_playwright"]
        if not final:
            final = ["ready"]
        if any(bad in msg for bad in ("密碼", "password", "口令")):
            msg = _default_message(final, facts)
        return {
            "facts": facts,
            "steps": final,
            "message_zh": msg or _default_message(final, facts),
            "source": "config+llm",
        }
    return {
        "facts": facts,
        "steps": steps,
        "message_zh": _default_message(steps, facts),
        "source": "config+rules",
    }


def _default_message(steps: list[str], facts: dict[str, Any]) -> str:
    title = facts.get("site_title") or facts.get("site_id") or "網站"
    if steps == ["ready"]:
        return f"{title} 已就緒，可以直接使用。"
    parts = [f"設定 {title}："]
    for s in steps:
        if s == "install_playwright":
            parts.append("安裝瀏覽器引擎 (Playwright Chromium)")
        elif s in ("auth_login", "auth_login_or_import"):
            parts.append("在專用視窗登入（只存 session）")
        elif s == "ready":
            parts.append("完成")
    return " → ".join(parts)
