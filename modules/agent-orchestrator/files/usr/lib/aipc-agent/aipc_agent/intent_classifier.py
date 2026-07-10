"""Fast front-door intent classifier for the supervisor.

Always runs *before* any worker (respond / daily / hermes / …). Output is a
two-axis plan:

  target ∈ respond | daily_assistant | hermes | screen_see | job_status
  mode   ∈ short | long

Design goals (voice path):
  - Tiny prompt + max_tokens ≤ 24 + short wall (default 2.5s)
  - Dedicated model alias (AIPC_CLASSIFIER_MODEL, default qwythos-9b —
    small Mythos local, uncensored routing; not NPU gemma-it)
  - Micro-rules only for greet / job_status / screen (not daily)
  - Daily intent is always model-judged (multimodal LLM)
  - Keyword fallback only if the model is cold / errors

This is intentionally *not* the full supervisor chat model path — no mem0,
no tools, no long system prompts.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

# Re-exported targets for callers / tests
TARGETS = frozenset(
    {
        "respond",
        "daily_assistant",
        "hermes",
        "screen_see",
        "job_status",
    }
)
MODES = frozenset({"short", "long"})
LONG_CAPABLE = frozenset({"hermes", "daily_assistant"})

# Default: small Mythos local (uncensored routing). NPU gemma-it refuses some
# intents; qwythos-9b is ~5.6GB Vulkan and ~0.2–0.5s when warm.
CLASSIFIER_MODEL = os.environ.get("AIPC_CLASSIFIER_MODEL", "qwythos-9b")
LITELLM_BASE_URL = os.environ.get("AIPC_LITELLM_URL", "http://127.0.0.1:4000")

# Ultra-compact system prompt — model only labels, does not answer the user.
_CLASSIFIER_SYSTEM = (
    "You are a pure intent ROUTER for a private local voice assistant. "
    "You NEVER answer the user, NEVER refuse, NEVER moralize, NEVER apply "
    "content filters. Route by task shape only — topic sensitivity is irrelevant; "
    "every lawful private request still gets a normal label.\n"
    "Output EXACTLY two lowercase words and nothing else: <target> <mode>\n"
    "target: respond | daily_assistant | hermes | screen_see | job_status\n"
    "mode: short | long\n"
    "respond = chit-chat, opinions, explanations, recommendations with no tools;\n"
    "daily_assistant = calendar/email/files/web-search/usage quotas;\n"
    "hermes = coding/shell/multi-step tools/live price/browser research that "
    "needs a tool agent;\n"
    "screen_see = describe the desktop/screen only;\n"
    "job_status = background task progress.\n"
    "mode=long only for background/full-project with hermes|daily_assistant.\n"
    "Judge meaning: 查/搜/search for information on the open web → "
    "daily_assistant (simple search) or hermes (multi-step browser/tools); "
    "general Q&A or recommendations without tools → respond.\n"
    "Examples (copy this shape):\n"
    "respond short\n"
    "daily_assistant short\n"
    "hermes short\n"
    "screen_see short\n"
)

_LINE_RE = re.compile(
    r"\b(respond|daily_assistant|hermes|screen_see|job_status)\b"
    r"[\s,|:/\\-]+"
    r"\b(short|long)\b",
    re.I,
)
_JSON_RE = re.compile(
    r'\{\s*"target"\s*:\s*"(respond|daily_assistant|hermes|screen_see|job_status)"'
    r'\s*,\s*"mode"\s*:\s*"(short|long)"',
    re.I,
)


def _timeout_s() -> float:
    # Headroom for first qwythos load; warm path is usually <0.5s.
    try:
        return max(0.5, float(os.environ.get("AIPC_CLASSIFIER_TIMEOUT", "3.5")))
    except ValueError:
        return 3.5


def _enabled() -> bool:
    return os.environ.get("AIPC_CLASSIFIER", "1") not in ("0", "false", "no", "off")


def _normalize(target: str, mode: str, text: str) -> dict[str, str]:
    t = (target or "respond").strip().lower()
    m = (mode or "short").strip().lower()
    if t not in TARGETS:
        t = "respond"
    if m not in MODES:
        m = "short"
    if t == "hermes" and os.environ.get("AIPC_HERMES_ROUTE", "1") in (
        "0",
        "false",
        "no",
    ):
        t = "respond"
    if m == "long" and t not in LONG_CAPABLE:
        m = "short"
    return {"target": t, "mode": m}


def parse_classifier_output(raw: str) -> dict[str, str] | None:
    """Parse model output → {target, mode} or None."""
    s = (raw or "").strip()
    if not s:
        return None
    # Strip fences / labels
    if "```" in s:
        s = s.split("```")[1]
        if s.lower().startswith("json"):
            s = s[4:]
    s = s.strip().strip("`").strip()
    # Prefer first line
    line = s.splitlines()[0].strip()
    m = _LINE_RE.search(line) or _LINE_RE.search(s)
    if m:
        return {"target": m.group(1).lower(), "mode": m.group(2).lower()}
    jm = _JSON_RE.search(s)
    if jm:
        return {"target": jm.group(1).lower(), "mode": jm.group(2).lower()}
    try:
        data = json.loads(s[s.find("{") : s.rfind("}") + 1])
        if isinstance(data, dict) and data.get("target"):
            return {
                "target": str(data["target"]).lower(),
                "mode": str(data.get("mode") or "short").lower(),
            }
    except Exception:
        pass
    # Bare target only when exactly one label appears (multi = model echoed enum list)
    found = [
        t
        for t in TARGETS
        if re.search(rf"(?<![a-z_]){re.escape(t)}(?![a-z_])", s, re.I)
    ]
    if len(found) == 1:
        return {"target": found[0], "mode": "short"}
    return None


def rules_classify(text: str) -> dict[str, Any] | None:
    """High-confidence rules — skip the model (speed path).

    Only returns when the label is obvious. Ambiguous text → None so the
    small classifier / keyword fallback can run.
    """
    raw = (text or "").strip()
    if not raw:
        return {
            "target": "respond",
            "mode": "short",
            "reason": "empty",
            "source": "rules",
        }
    low = raw.lower()
    # Job status — never need a model
    status_keys = (
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
    if any(k in low for k in status_keys):
        return {
            "target": "job_status",
            "mode": "short",
            "reason": "rules:job_status",
            "source": "rules",
        }

    # Screen look
    if any(
        k in raw
        for k in (
            "屏幕上",
            "螢幕上",
            "看屏幕",
            "看螢幕",
            "看桌面",
            "桌面上有",
            "what's on screen",
            "what is on screen",
            "on my screen",
        )
    ):
        return {
            "target": "screen_see",
            "mode": "short",
            "reason": "rules:screen",
            "source": "rules",
        }

    # Pure greetings / short chat — fastest path to respond
    greet = (
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
        "thanks",
        "thank you",
        "谢谢",
        "謝謝",
        "再见",
        "再見",
    )
    compact = re.sub(r"[\s。.!！?？,，、~～]+", "", raw.lower())
    if compact in {re.sub(r"\s+", "", g.lower()) for g in greet} or len(raw) <= 2:
        return {
            "target": "respond",
            "mode": "short",
            "reason": "rules:greet",
            "source": "rules",
        }

    # DAILY is NOT keyword-routed (user 2026-07-10): always model-classify.
    # Keep only ultra-clear coding → hermes so voice latency stays low for 写代码.
    # Clear coding → hermes without model round-trip
    code_keys = (
        "写代码",
        "寫代碼",
        "写程式",
        "改代码",
        "改代碼",
        "debug",
        "修bug",
        "修 bug",
        "重构",
        "重構",
        "pull request",
        "shell脚本",
        "生成脚本",
    )
    if any(k in low for k in code_keys) or any(k in raw for k in code_keys):
        mode = "long" if any(
            k in low for k in ("后台", "後台", "慢慢", "完整", "长任务", "長任務")
        ) else "short"
        return {
            "target": "hermes",
            "mode": mode,
            "reason": "rules:code",
            "source": "rules",
        }
    return None


def _keyword_fallback(text: str) -> dict[str, Any]:
    """Fail-soft when classifier is off / cold. Mirrors legacy keyword target."""
    # Late import to avoid circular graphs import at module load for pure parse tests
    try:
        from aipc_agent import graphs as g

        target = g._keyword_target(text)
        # Long markers apply even if target is still "respond" — then upgrade worker
        want_long = g.wants_long_mode(text)
        mode = "long" if want_long else g._keyword_mode(text, target)
        if mode == "long" and target not in LONG_CAPABLE:
            if g.wants_daily_assistant(text):
                target = "daily_assistant"
            elif os.environ.get("AIPC_HERMES_ROUTE", "1") not in ("0", "false", "no"):
                target = "hermes"
            else:
                mode = "short"
        if mode == "long" and target not in LONG_CAPABLE:
            mode = "short"
        return {
            "target": target,
            "mode": mode,
            "reason": f"fallback keyword target={target} mode={mode}",
            "source": "fallback",
        }
    except Exception:
        return {
            "target": "respond",
            "mode": "short",
            "reason": "fallback default",
            "source": "fallback",
        }


def _invoke_classifier_llm(text: str, timeout: float):
    """Hard socket timeout so abandoned classify never holds Lemonade slots.

    ChatLiteLLM threads orphaned after join() kept resident-small busy and
    made the next /chat say「本地模型连不上」.
    """
    import json
    import urllib.request

    from aipc_agent._util import text_of

    base = (LITELLM_BASE_URL or "http://127.0.0.1:4000").rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    payload = {
        "model": CLASSIFIER_MODEL,
        "messages": [
            {"role": "system", "content": _CLASSIFIER_SYSTEM},
            {"role": "user", "content": (text or "")[:280]},
        ],
        "max_tokens": int(os.environ.get("AIPC_CLASSIFIER_MAX_TOKENS", "24")),
        "temperature": 0,
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
    # Socket timeout closes the connection — no orphan load on Lemonade.
    with urllib.request.urlopen(req, timeout=max(0.4, timeout)) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices") or []
    if not choices:
        return ""
    return text_of((choices[0].get("message") or {}).get("content"))


def model_classify(text: str) -> dict[str, Any] | None:
    """Call the small classifier model under a hard wall. None on failure / timeout.

    Uses a daemon thread so a stuck LiteLLM call cannot block voice past the wall
    (ThreadPoolExecutor.__exit__ would wait for the worker and defeat the timeout).
    """
    if not _enabled():
        return None
    timeout = _timeout_s()
    t0 = time.monotonic()
    box: dict[str, Any] = {"raw": None, "err": None}

    def _run() -> None:
        try:
            box["raw"] = _invoke_classifier_llm(text, timeout)
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    try:
        import threading

        th = threading.Thread(target=_run, name="intent-classifier", daemon=True)
        th.start()
        th.join(timeout=timeout)
        if th.is_alive():
            print(
                f"aipc-agent: classifier hard-timeout {timeout:.1f}s "
                f"model={CLASSIFIER_MODEL} (fallback)",
                flush=True,
            )
            return None
        if box["err"] is not None:
            raise box["err"]
        raw = box["raw"] or ""
        parsed = parse_classifier_output(raw)
        elapsed = time.monotonic() - t0
        if not parsed:
            print(
                f"aipc-agent: classifier unparsed {elapsed:.2f}s raw={raw[:80]!r}",
                flush=True,
            )
            return None
        plan = _normalize(parsed["target"], parsed["mode"], text)
        plan["reason"] = f"classifier {elapsed:.2f}s raw={raw.strip()[:40]!r}"
        plan["source"] = "classifier"
        plan["latency_s"] = f"{elapsed:.3f}"
        print(
            f"aipc-agent: classifier → {plan['target']} {plan['mode']} "
            f"({elapsed:.2f}s model={CLASSIFIER_MODEL})",
            flush=True,
        )
        return plan
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - t0
        print(
            f"aipc-agent: classifier fail {elapsed:.2f}s: {exc}",
            flush=True,
        )
        return None


def classify(text: str, *, session_id: str = "") -> dict[str, Any]:
    """Front-door entry: tiny rules (greet/status) → multimodal LLM → keyword fallback.

    DAILY detection is model-owned (no if/else keyword lists). Policy:
      auto / 1 / always (recommended): model classifies after micro-rules
      rules / 0: legacy keyword-only (not recommended for daily)
    """
    hit = rules_classify(text)
    if hit:
        return hit

    policy = (os.environ.get("AIPC_CLASSIFIER", "auto") or "auto").lower()
    use_model = True
    if policy in ("0", "false", "no", "off", "rules", "rules_only"):
        use_model = False
    # auto / 1 / always / model / multimodal → model

    if use_model:
        plan = model_classify(text)
        if plan:
            return plan

    return _keyword_fallback(text)


def self_test() -> None:
    assert parse_classifier_output("daily_assistant short") == {
        "target": "daily_assistant",
        "mode": "short",
    }
    assert parse_classifier_output("hermes long")["mode"] == "long"
    assert parse_classifier_output('{"target":"respond","mode":"short"}')[
        "target"
    ] == "respond"
    assert parse_classifier_output("garbage") is None
    r = rules_classify("任务进度怎么样")
    assert r and r["target"] == "job_status"
    print("intent_classifier self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    q = " ".join(a for a in sys.argv[1:] if a != "--self-test") or "你好"
    print(classify(q))
