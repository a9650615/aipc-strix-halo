"""Deterministic capability analysis (typed dimensions only — no topic censor).

Labels: required capabilities, freshness, risk, data_scope hints, request class,
optional explicit provider override. Never refuses by topic keyword.
"""

from __future__ import annotations

import re
from typing import Any

from aipc_agent.router.schemas import validate_envelope

# Explicit provider override (user named a provider) — still subject to grants later
_PROVIDER_RE = re.compile(
    r"(?i)\b("
    r"codex|claude\s*code|claude|hermes|chatgpt|gpt-?4|gemini|grok|"
    r"用\s*codex|用\s*claude|用\s*hermes|用\s*chatgpt"
    r")\b"
)

# Freshness / live grounding (capability, not censorship)
_LIVE_RE = re.compile(
    r"(?i)("
    r"股价|股價|行情|现价|現價|报价|報價|台风|颱風|天气|天氣|新闻|新聞|"
    r"最新|实时|即時|今天|今日|现在|現在|live\b|price\b|stock\b|weather\b|"
    r"typhoon|news\b|availability|库存|庫存"
    r")"
)

# Local tool workers
_USAGE_RE = re.compile(r"(?i)(用量|额度|額度|quota|usage|token\s*用|还有多少|還有多少)")
_CAL_RE = re.compile(r"(?i)(日历|日曆|行程|日程|calendar|会议|會議|appointment)")
_MAIL_RE = re.compile(r"(?i)(邮件|郵件|email|inbox|收件)")
_FILE_RE = re.compile(r"(?i)(打开文件|打開文件|读文件|讀文件|写文件|寫文件|delete file|删文件|刪文件)")
_SCREEN_RE = re.compile(r"(?i)(屏幕|螢幕|桌面|screen|看一下屏幕|描述屏幕)")
_JOB_RE = re.compile(r"(?i)(任务进度|任務進度|job status|后台任务|後台任務|跑完了吗|跑完了嗎)")
_CODE_RE = re.compile(
    r"(?i)("
    r"写代码|寫代碼|写程式|寫程式|写个|寫個|写一|寫一|实现|實現|refactor|debug|"
    r"修bug|改\s*bug|改bug|单元测试|單元測試|排序|快速排序|登录|登入|"
    r"function\b|class\b|python|typescript|编译|編譯"
    r")"
)
_SEARCH_RE = re.compile(
    r"(?i)("
    r"查一下|搜一下|搜索|搜尋|google|查查|帮我查|幫我查|search\b|look up|"
    r"网上|網上|网页|網頁"
    r")"
)
_CTRL_RE = re.compile(
    r"(?i)("
    r"^(几点|幾點|几点了|幾點了|mute|unmute|静音|靜音|音量|"
    r"打开面板|打開面板|open portal|open dashboard|现在几点|現在幾點)$"
    r")"
)
_GREET_RE = re.compile(
    r"(?i)^("
    r"你好|您好|嗨|hi|hello|hey|在吗|在嗎|早|晚安|再见|再見|bye"
    r")[\s!！.。?？]*$"
)


def _provider_token(m: str) -> str:
    s = re.sub(r"\s+", " ", m.strip().lower())
    s = s.replace("用 ", "").replace("用", "")
    if "codex" in s:
        return "codex-subscription"
    if "claude" in s:
        return "claude-subscription"
    if "hermes" in s:
        return "hermes"
    if "chatgpt" in s or "gpt" in s:
        return "chatgpt-online"
    if "gemini" in s:
        return "gemini-metered"
    if "grok" in s:
        return "grok-subscription"
    return s


def analyze(envelope: dict[str, Any]) -> dict[str, Any]:
    """Mutate a copy of envelope with required/freshness/risk/class hints.

    Returns analysis dict with envelope fields + reason_codes + request_class.
    """
    env = validate_envelope(dict(envelope))
    text = (env.get("text") or "").strip()
    compact = re.sub(r"\s+", "", text)
    required: list[str] = ["chat"]
    freshness = "none"
    risk = "read"
    scopes = list(env.get("data_scopes") or ["prompt"])
    reasons: list[str] = []
    explicit = ""
    conf = 0.55

    pm = _PROVIDER_RE.search(text)
    if pm:
        explicit = _provider_token(pm.group(1))
        reasons.append("explicit_provider")
        conf = 0.9

    if _GREET_RE.match(text) or _CTRL_RE.match(compact) or _CTRL_RE.match(text.strip()):
        required = ["deterministic_local"]
        reasons.append("l0_control_or_greet")
        conf = 0.95
        req_class = "L0"
    elif _JOB_RE.search(text):
        required = ["job_status"]
        reasons.append("job_status")
        conf = 0.9
        req_class = "L1"
    elif _SCREEN_RE.search(text):
        required = ["screen"]
        risk = "read"
        if "screen" not in scopes:
            scopes.append("screen")
        reasons.append("screen")
        conf = 0.9
        req_class = "L2"
    elif _USAGE_RE.search(text):
        required = ["usage_tools"]
        reasons.append("usage")
        conf = 0.92
        req_class = "L2"
    elif _CAL_RE.search(text) or _MAIL_RE.search(text):
        required = ["daily_tools"]
        if _MAIL_RE.search(text) and "email" not in scopes:
            scopes.append("email")
        if _CAL_RE.search(text) and "calendar" not in scopes:
            scopes.append("calendar")
        reasons.append("daily_personal")
        conf = 0.85
        req_class = "L2"
    elif _FILE_RE.search(text):
        required = ["files"]
        risk = "write" if re.search(r"(?i)(写|寫|delete|删|刪)", text) else "read"
        reasons.append("files")
        conf = 0.85
        req_class = "L2"
    elif _LIVE_RE.search(text) or _SEARCH_RE.search(text):
        required = ["web_search", "grounding"]
        freshness = "live" if _LIVE_RE.search(text) else "recent"
        reasons.append("live_or_search")
        conf = 0.8
        req_class = "L2"
    elif _CODE_RE.search(text):
        required = ["coding", "tools"]
        risk = "write"
        reasons.append("coding")
        conf = 0.8
        req_class = "L3"
    else:
        required = ["chat"]
        reasons.append("default_chat")
        conf = 0.5
        req_class = "L1"

    # Product-style codes → force tool lookup (reuse grounding if available)
    try:
        from aipc_agent.grounding import needs_tool_lookup

        if needs_tool_lookup(text) and "grounding" not in required:
            required = list(dict.fromkeys([*required, "web_search", "grounding"]))
            freshness = "live" if freshness == "none" else freshness
            reasons.append("catalog_code")
            conf = max(conf, 0.85)
            if req_class == "L1":
                req_class = "L2"
    except Exception:
        pass

    env["required"] = required
    env["freshness"] = freshness
    env["risk"] = risk
    env["data_scopes"] = scopes
    env["explicit_provider"] = explicit
    return {
        **env,
        "request_class": req_class,
        "confidence": conf,
        "reason_codes": reasons,
    }
