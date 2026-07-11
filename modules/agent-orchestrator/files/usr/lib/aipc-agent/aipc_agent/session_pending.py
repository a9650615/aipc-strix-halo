"""Per-session pending clarifications + one-shot prompt/task parsing.

One-shot (preferred for voice):
  「用 Hermes 帮我写快速排序」
  「提示词：你是严谨工程师。任务：重构 auth 模块」
  「system: be concise. task: implement binary search」

Secondary clarify only when the utterance is bare coding intent
(e.g. just「帮我写代码」) with no agent and no concrete task body.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_PENDING: dict[str, dict[str, Any]] = {}

TTL_S = float(os.environ.get("AIPC_CLARIFY_TTL_S", "180"))
_PENDING_DIR = Path(os.environ.get("AIPC_PENDING_DIR", "/var/lib/aipc-agent/pending"))
_PENDING_PERSIST = os.environ.get("AIPC_PENDING_PERSIST", "1") not in ("0", "false", "no")
# Auto: only ask when incomplete; off: never ask; always: always ask for coding
CLARIFY_MODE = (os.environ.get("AIPC_CLARIFY", "auto") or "auto").lower()

CODING_AGENTS: list[dict[str, str]] = [
    {
        "id": "hermes",
        "label": "Hermes",
        "hint": "工具代理，能写文件、跑命令",
        "aliases": (
            "hermes",
            "赫米斯",
            "工具代理",
            "工具 agent",
            "hermes 工具",
        ),
    },
    {
        "id": "coder-agentic",
        "label": "coder-agentic",
        "hint": "本地编码模型",
        "aliases": (
            "coder-agentic",
            "coder agentic",
            "本地编码",
            "本地編碼",
            "本地 coder",
            "本地模型",
            "agentic",
        ),
    },
    {
        "id": "coder-cloud",
        "label": "coder-cloud",
        "hint": "云端编码",
        "aliases": (
            "coder-cloud",
            "coder cloud",
            "云端",
            "雲端",
            "云端编码",
            "雲端編碼",
            "cloud coder",
        ),
    },
]

# Bare choice reply only (second turn)
_CHOICE_ALIASES: dict[str, tuple[str, ...]] = {
    "hermes": ("1", "一", "壹", "第一个", "第一個"),
    "coder-agentic": ("2", "二", "贰", "第二个", "第二個"),
    "coder-cloud": ("3", "三", "叁", "第三个", "第三個"),
}


def clarify_enabled() -> bool:
    return CLARIFY_MODE not in ("0", "false", "no", "off")


def _pending_path(sid: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in sid)[:80]
    return _PENDING_DIR / f"{safe}.json"


def _load_pending(sid: str) -> dict[str, Any] | None:
    if not _PENDING_PERSIST:
        return None
    p = _pending_path(sid)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, NameError):
        return None
    return data if isinstance(data, dict) else None


def _save_pending(sid: str, data: dict[str, Any]) -> None:
    if not _PENDING_PERSIST:
        return
    try:
        _PENDING_DIR.mkdir(parents=True, exist_ok=True)
        p = _pending_path(sid)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _unlink_pending(sid: str) -> None:
    if not _PENDING_PERSIST:
        return
    try:
        p = _pending_path(sid)
        if p.is_file():
            p.unlink()
    except OSError:
        pass


def get(session_id: str) -> dict[str, Any] | None:
    sid = (session_id or "").strip() or "default"
    disk = _load_pending(sid)
    with _LOCK:
        mem = _PENDING.get(sid)
        p = None
        if disk and mem:
            if float(disk.get("ts") or 0) >= float(mem.get("ts") or 0):
                p = disk
                _PENDING[sid] = disk
            else:
                p = mem
        elif disk:
            p = disk
            _PENDING[sid] = disk
        elif mem:
            p = mem
        if not p:
            return None
        if time.time() - float(p.get("ts") or 0) > TTL_S:
            _PENDING.pop(sid, None)
            _unlink_pending(sid)
            return None
        return dict(p)


def set_pending(session_id: str, payload: dict[str, Any]) -> None:
    sid = (session_id or "").strip() or "default"
    data = dict(payload)
    data["ts"] = time.time()
    data["session_id"] = sid
    with _LOCK:
        _PENDING[sid] = data
    _save_pending(sid, data)


def clear(session_id: str) -> None:
    sid = (session_id or "").strip() or "default"
    with _LOCK:
        _PENDING.pop(sid, None)
    _unlink_pending(sid)


def is_cancel(text: str) -> bool:
    low = (text or "").strip().lower()
    return any(
        k in low
        for k in (
            "取消",
            "算了",
            "不要了",
            "不用了",
            "stop",
            "cancel",
            "never mind",
            "算了吧",
        )
    )


def _coding_signal(text: str) -> bool:
    try:
        from aipc_agent import graphs as g

        return bool(g.wants_hermes(text))
    except Exception:
        raw = (text or "").lower()
        return any(
            k in raw
            for k in (
                "写代码",
                "寫代碼",
                "写程式",
                "改代码",
                "debug",
                "修bug",
                "实现",
                "實現",
                "refactor",
            )
        )


def explicit_coding_agent(text: str) -> str | None:
    """If user named an agent in the utterance, return its id."""
    raw = text or ""
    low = raw.lower()
    if not low:
        return None
    ranked: list[tuple[int, str]] = []
    for ag in CODING_AGENTS:
        for a in ag["aliases"]:
            if a.lower() in low or a in raw:
                ranked.append((len(a), ag["id"]))
    if ranked:
        ranked.sort(reverse=True)
        return ranked[0][1]
    # Patterns: 用 X / 交给 X / via X / with X
    m = re.search(
        r"(?:用|交給|交给|请|請|via|with|use)\s*"
        r"(hermes|赫米斯|coder-?agentic|coder-?cloud|本地编码|本地編碼|云端|雲端)",
        low,
        re.I,
    )
    if m:
        return parse_agent_choice(m.group(1))
    if "用hermes" in low or "交给hermes" in low or "交給hermes" in low:
        return "hermes"
    return None


def parse_prompt_and_task(text: str) -> dict[str, str] | None:
    """Parse 提示词+任务 / system+task in one utterance.

    Returns {system, task} or None.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    patterns = [
        # 提示词：... 任务：...
        r"(?:提示词|提示詞|系统提示|系統提示|system\s*prompt|prompt)\s*[:：]\s*(.+?)\s*"
        r"(?:任务|任務|task)\s*[:：]\s*(.+)$",
        # 任务：... 提示词：... (reversed)
        r"(?:任务|任務|task)\s*[:：]\s*(.+?)\s*"
        r"(?:提示词|提示詞|系统提示|系統提示|system\s*prompt|prompt)\s*[:：]\s*(.+)$",
        # English system: ... task: ...
        r"system\s*[:：]\s*(.+?)\s*task\s*[:：]\s*(.+)$",
    ]
    for i, pat in enumerate(patterns):
        m = re.search(pat, raw, re.I | re.S)
        if not m:
            continue
        a, b = m.group(1).strip(), m.group(2).strip()
        if i == 1:  # reversed
            task, system = a, b
        else:
            system, task = a, b
        if system and task:
            return {"system": system, "task": task}
    return None


def strip_agent_boilerplate(text: str) -> str:
    """Remove agent-pick phrases so the worker gets the clean task."""
    t = text or ""
    # 用 X 帮我 / 交给 X
    t = re.sub(
        r"(用|交給|交给|请用|請用|via|with|use)\s*"
        r"(hermes|赫米斯|coder-?agentic|coder-?cloud|本地编码|本地編碼|云端编码|雲端編碼|云端|雲端|工具代理)"
        r"\s*(帮我|幫我|来|來)?",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s+", " ", t).strip(" ，,。")
    return t or (text or "").strip()


def compose_task_text(*, system: str = "", task: str = "", raw: str = "") -> str:
    """Build worker input: optional system block + task."""
    task = (task or raw or "").strip()
    system = (system or "").strip()
    if system and task:
        return f"[System instructions]\n{system}\n\n[User task]\n{task}"
    return task


def _oneshot_mode(raw: str, body: str = "") -> str:
    """Respect long-task markers (后台/慢慢做/完整实现…) on one-shot paths."""
    try:
        from aipc_agent.graphs import wants_long_mode

        if wants_long_mode(raw) or wants_long_mode(body):
            return "long"
    except Exception:
        pass
    # Very long prompt+task blobs are better as background
    if len(body or raw or "") > 120:
        return "long"
    return "short"


def parse_oneshot(text: str) -> dict[str, Any] | None:
    """One utterance = agent (optional) + prompt (optional) + task.

    Returns plan fields: agent, original_text (for worker), mode hint, or None
    if this is not a complete one-shot coding request.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # Daily tools (用量/日历/邮件) must not become Hermes oneshots just because
    # wants_hermes has broad web keywords (帮我查 / 最新 …).
    try:
        from aipc_agent.graphs import wants_daily_assistant

        if wants_daily_assistant(raw):
            low = raw.lower()
            named = explicit_coding_agent(raw)
            coding_kw = any(
                k in raw or k in low
                for k in (
                    "写代码",
                    "寫代碼",
                    "改代码",
                    "debug",
                    "修bug",
                    "脚本",
                    "腳本",
                    "实现",
                    "實現",
                    "refactor",
                )
            )
            if not named and not coding_kw and "hermes" not in low and "赫米斯" not in raw:
                return None
    except Exception:
        pass

    pt = parse_prompt_and_task(raw)
    agent = explicit_coding_agent(raw)

    if pt:
        # 提示词+任务 once: default Hermes (tooling) unless another agent named
        ag = agent or "hermes"
        body = compose_task_text(system=pt["system"], task=pt["task"])
        return {
            "agent": ag,
            "original_text": body,
            "mode": _oneshot_mode(raw, body),
            "reason": "oneshot:prompt+task",
        }

    if agent:
        body = strip_agent_boilerplate(raw)
        # Named agent + leftover task (or coding keywords) → run now
        if _coding_signal(raw) or (body and body != raw.strip() and len(body) >= 2):
            return {
                "agent": agent,
                "original_text": body or raw,
                "mode": _oneshot_mode(raw, body or raw),
                "reason": f"oneshot:agent+task:{agent}",
            }

    # Full coding task without agent name → default Hermes, no ask
    # (user already said the task in one breath)
    if _coding_signal(raw) and _has_concrete_task(raw):
        return {
            "agent": "hermes",
            "original_text": raw,
            "mode": _oneshot_mode(raw),
            "reason": "oneshot:task-default-hermes",
        }

    return None


def _has_concrete_task(text: str) -> bool:
    """True if more than bare '写代码' — has a real task body."""
    t = (text or "").strip()
    if len(t) >= 12:
        return True
    # Strip openers only — keep 实现/重构 as part of the task body
    stripped = re.sub(
        r"(帮我|幫我|请|請|用hermes|用\s*hermes|写代码|寫代碼|写程式|改代码|改代碼|"
        r"debug|修\s*bug)",
        "",
        t,
        flags=re.I,
    )
    stripped = re.sub(r"\s+", "", stripped)
    return len(stripped) >= 2


def needs_coding_agent_clarify(text: str) -> bool:
    """Only when coding is bare and incomplete (no agent, no real task)."""
    if not clarify_enabled():
        return False
    if CLARIFY_MODE in ("0", "false", "no", "off"):
        return False
    if CLARIFY_MODE in ("always", "1", "true", "on"):
        return _coding_signal(text) and not explicit_coding_agent(text)
    # auto (default): one-shot complete → never ask
    if parse_oneshot(text):
        return False
    if not _coding_signal(text):
        return False
    if explicit_coding_agent(text):
        return False
    # Bare "帮我写代码" / "debug" without body
    return not _has_concrete_task(text)


def coding_agent_question() -> str:
    return (
        "写代码可以走：一、Hermes 工具代理；二、本地 coder-agentic；"
        "三、云端 coder-cloud。也可以一次说完，例如："
        "用 Hermes 帮我写快速排序；或 提示词：简洁。任务：实现登录。"
    )


def parse_agent_choice(text: str) -> str | None:
    """Map user reply (or fragment) to agent id."""
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.lower()
    # Bare 1/2/3 only as pure reply
    for ag_id, aliases in _CHOICE_ALIASES.items():
        for a in aliases:
            if low == a or low == a.lower():
                return ag_id
    for ag in CODING_AGENTS:
        for a in ag["aliases"]:
            if a.lower() in low or a in raw:
                return ag["id"]
    for ag_id, aliases in _CHOICE_ALIASES.items():
        for a in aliases:
            if a in raw or a.lower() in low:
                return ag_id
    if re.search(r"(hermes|赫米斯|工具代理)", low):
        return "hermes"
    if re.search(r"(coder-?agentic|本地编码|本地編碼|本地模型)", low):
        return "coder-agentic"
    if re.search(r"(coder-?cloud|云端|雲端)", low):
        return "coder-cloud"
    return None


def start_coding_clarify(
    session_id: str, original_text: str, *, mode: str = "short"
) -> dict[str, Any]:
    q = coding_agent_question()
    set_pending(
        session_id,
        {
            "kind": "coding_agent",
            "original_text": original_text,
            "mode": mode if mode in ("short", "long") else "short",
            "question": q,
        },
    )
    return {
        "target": "clarify",
        "mode": "short",
        "reason": "clarify:coding_agent",
        "source": "clarify",
        "clarify_question": q,
        "agent": "",
        "original_text": original_text,
    }


def plan_from_oneshot(oneshot: dict[str, Any]) -> dict[str, Any]:
    """Map oneshot parse → dispatch plan."""
    agent = oneshot.get("agent") or "hermes"
    if agent == "hermes":
        target = "hermes"
    else:
        target = "coder"
    return {
        "target": target,
        "mode": oneshot.get("mode") or "short",
        "reason": oneshot.get("reason") or "oneshot",
        "source": "oneshot",
        "agent": agent,
        "original_text": oneshot.get("original_text") or "",
        "clarify_question": "",
    }




# --- tool slot-fill (stock / web lookup) for multi-turn voice ---

_STOCK_KEYS = (
    "股价", "股價", "股票", "行情", "市值", "涨跌", "漲跌",
    "stock", "ticker", "share price", "stock price",
)

# Known liquid tickers only for history recovery (no free [A-Z]{1,5} —
# that matched "None"/"HTTP" inside LLM error dumps and poisoned follow-ups).
_KNOWN_TICKERS = (
    "AMD", "NVDA", "AAPL", "MSFT", "GOOG", "GOOGL", "META", "TSLA", "AMZN",
    "INTC", "TSM", "AVGO", "QCOM", "ARM", "BABA", "PDD", "NIO", "XPEV", "LI",
    "SMCI", "PLTR", "COIN", "HOOD", "RIVN", "IBM", "ORCL", "NFLX", "DIS",
    "BA", "JPM", "V", "MA", "WMT", "KO", "PEP", "COST", "CRM", "ADBE", "MU",
)
_TICKER_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    + "|".join(_KNOWN_TICKERS)
    + r"|\^[A-Z]{1,5}"
    + r")(?![A-Za-z0-9])",
    re.I,
)
_TICKER_JUNK = frozenset(
    {
        "NONE", "NULL", "TRUE", "FALSE", "HTTP", "HTTPS", "ERROR", "API",
        "JSON", "HTML", "TEXT", "USER", "ASSIST", "MODEL", "GROUP", "FALL",
        "OPEN", "FAIL", "RETRY", "TOKEN", "CHAT", "ROLE",
    }
)

# Chinese company names commonly used in speech
_STOCK_NAMES = (
    "英伟达", "英偉達", "苹果", "蘋果", "微软", "微軟", "谷歌", "特斯拉",
    "台积电", "台積電", "亚马逊", "亞馬遜", "美光", "高通", "博通",
    "阿里", "阿里巴巴", "腾讯", "騰訊", "茅台", "宁德", "寧德",
)


def looks_like_stock_query(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if any(k in raw for k in _STOCK_KEYS) or any(k in low for k in ("stock", "ticker")):
        return True
    # 「查一下AMD」without 股价 still often means stock on this machine
    if re.search(r"(查|搜).{0,6}(股|票|价|價|行情)", raw):
        return True
    return False


def _clean_ticker(sym: str | None) -> str | None:
    if not sym:
        return None
    s = str(sym).upper().lstrip("^").strip()
    if not s or s in _TICKER_JUNK:
        return None
    if s in _KNOWN_TICKERS:
        return s
    # bare short Latin reply allowed if not junk
    if re.fullmatch(r"[A-Z]{1,5}", s) and s not in _TICKER_JUNK:
        return s
    return None


def extract_stock_symbol(text: str) -> str | None:
    """Best-effort ticker or company name from utterance."""
    raw = (text or "").strip()
    if not raw:
        return None
    for name in _STOCK_NAMES:
        if name in raw:
            return name
    m = _TICKER_RE.search(raw)
    if m:
        return _clean_ticker(m.group(1))
    # bare short reply: AMD / 台积电 (not full queries like 查股价)
    t = re.sub(r"[\s。.!！?？,，、]+", "", raw)
    if re.fullmatch(r"[A-Za-z]{1,5}", t):
        return _clean_ticker(t)
    # Reject query shells that contain stock keywords but no company name
    if any(k in t for k in ("股价", "股價", "股票", "行情", "市值", "查一下", "帮我", "幫我")):
        return None
    if any(t.startswith(v) for v in ("查", "搜", "看", "问", "問", "帮", "幫", "那")):
        return None
    # Day/time follow-ups are not tickers
    if any(k in t for k in ("昨天", "昨日", "前天", "其他天", "上周", "上週", "开盘", "開盤", "收盘", "收盤")):
        return None
    # Farewell / cancel never a ticker
    if any(
        k in t
        for k in (
            "没事", "沒事", "再见", "再見", "拜拜", "晚安", "取消", "算了",
            "不用了", "bye", "ok", "好的", "谢谢", "謝謝",
        )
    ):
        return None
    # Only known Chinese company names — free 2–4 char CJK was matching 没事了
    for name in _STOCK_NAMES:
        if t == name or name in t:
            return name
    return None


def stock_task_text(symbol: str, extra: str = "") -> str:
    sym = (symbol or "").strip()
    base = (
        f"请用网络/浏览器工具查询 {sym} 的最新股价（含货币与涨跌若可得），"
        f"用一两句中文口语汇报，不要输出安装说明或命令。"
    )
    if extra and extra.strip() and extra.strip() not in (sym, f"查{sym}"):
        return f"{base} 用户原话：{extra.strip()[:80]}"
    return base


def needs_stock_slot(text: str) -> bool:
    """Stock intent but no symbol yet — ask once, then run Hermes."""
    if not looks_like_stock_query(text):
        return False
    return extract_stock_symbol(text) is None


def start_stock_slot(session_id: str, original_text: str, *, agent: str = "hermes") -> dict:
    q = "要查哪支股票？直接说代码或名称，比如 AMD、英伟达、台积电。"
    set_pending(
        session_id,
        {
            "kind": "stock_slot",
            "original_text": original_text,
            "agent": agent or "hermes",
            "mode": "short",
            "question": q,
        },
    )
    return {
        "target": "clarify",
        "mode": "short",
        "reason": "clarify:stock_slot",
        "source": "clarify",
        "clarify_question": q,
        "agent": agent or "hermes",
        "original_text": original_text,
    }


def _last_stock_symbol_from_history(blob: str) -> str | None:
    """Recover last ticker/name mentioned in recent dialogue text."""
    for name in _STOCK_NAMES:
        if name in blob:
            return name
    # Prefer known tickers from newest match (never free-form junk words)
    matches = list(_TICKER_RE.finditer(blob or ""))
    for m in reversed(matches):
        sym = _clean_ticker(m.group(1))
        if sym:
            return sym
    return None


def try_continue_stock_from_history(session_id: str, text: str) -> dict | None:
    """If recent turns were about stock/hermes and user gives a short follow-up.

    Handles:
      - bare symbol: AMD
      - same-symbol day follow-up: 那昨天呢 / 其他天 / 上周
    """
    raw_in = (text or "").strip()
    if not raw_in:
        return None
    # Never hijack farewell / cancel into a stock tool call
    compact = re.sub(r"[\s。.!！?？,，、]+", "", raw_in)
    if any(
        k in compact
        for k in (
            "没事", "沒事", "再见", "再見", "拜拜", "晚安", "取消", "算了",
            "不用了", "就这样", "就這樣", "bye", "stop", "结束", "結束",
        )
    ):
        return None
    try:
        from aipc_agent import agent_context
        from aipc_agent.memory import AGENT_CHAT
    except Exception:
        return None
    turns = agent_context.get_turns(session_id, AGENT_CHAT)
    if not turns:
        return None
    blob = " ".join((t.get("content") or "") for t in turns[-8:])
    if not any(
        k in blob.lower() or k in blob
        for k in (
            "股价",
            "股價",
            "股票",
            "行情",
            "hermes",
            "stock",
            "ticker",
            "查哪",
            "哪支",
            "美元",
        )
    ):
        return None

    compact = re.sub(r"[\s。.!！?？,，、]+", "", raw_in)
    day_follow = any(
        k in raw_in
        for k in (
            "昨天",
            "昨日",
            "前天",
            "其他天",
            "上周",
            "上週",
            "这周",
            "這週",
            "开盘",
            "開盤",
            "收盘",
            "收盤",
            "今早",
            "昨晚",
        )
    )

    # Day follow-ups must reuse prior symbol, never parse 昨天 as a ticker.
    if day_follow:
        sym = _last_stock_symbol_from_history(blob)
    else:
        sym = extract_stock_symbol(text)
    if not sym:
        return None

    # bare symbol or short day follow-up only
    if not day_follow:
        if len(compact) > 12 and looks_like_stock_query(text):
            return None
        if len(compact) > 12:
            return None

    if day_follow:
        task = (
            f"请用网络/浏览器工具查询 {sym} 在「{text.strip()[:40]}」所指时间的股价/表现"
            f"（相对上一次回复的最新价），用一两句中文口语汇报，不要输出安装说明。"
        )
        reason = "history:stock-day-followup"
    else:
        task = stock_task_text(sym, extra=text)
        reason = "history:stock-slot"
    return {
        "target": "hermes",
        "mode": "short",
        "reason": reason,
        "source": "history",
        "agent": "hermes",
        "original_text": task,
        "clarify_question": "",
    }


def try_resolve(session_id: str, text: str) -> dict[str, Any] | None:
    """If session has pending clarify, consume reply → dispatch plan or re-ask."""
    pending = get(session_id)
    if not pending:
        return None
    if is_cancel(text):
        clear(session_id)
        return {
            "target": "respond",
            "mode": "short",
            "reason": "clarify:cancelled",
            "source": "clarify",
            "clarify_question": "",
            "agent": "",
            "original_text": "",
            "force_text": "好的，已取消。",
        }
    kind = pending.get("kind") or ""
    if kind == "stock_slot":
        if looks_like_stock_query(text) and extract_stock_symbol(text):
            # full new stock query
            clear(session_id)
            sym = extract_stock_symbol(text)
            return {
                "target": "hermes",
                "mode": "short",
                "reason": "clarify:stock-full",
                "source": "clarify",
                "agent": pending.get("agent") or "hermes",
                "original_text": stock_task_text(sym or text, extra=text),
                "clarify_question": "",
            }
        sym = extract_stock_symbol(text)
        if not sym:
            return {
                "target": "clarify",
                "mode": "short",
                "reason": "clarify:stock-reask",
                "source": "clarify",
                "clarify_question": "还是没听清股票代码。请说例如 AMD、NVDA、台积电。",
                "agent": pending.get("agent") or "hermes",
                "original_text": pending.get("original_text") or "",
            }
        clear(session_id)
        return {
            "target": "hermes",
            "mode": "short",
            "reason": "clarify:stock-slot",
            "source": "clarify",
            "agent": pending.get("agent") or "hermes",
            "original_text": stock_task_text(sym, extra=str(pending.get("original_text") or "")),
            "clarify_question": "",
        }
    if kind == "coding_agent":
        # Second turn can also be full oneshot
        oneshot = parse_oneshot(text)
        if oneshot and oneshot.get("agent"):
            clear(session_id)
            # Prefer new full task if given; else keep original + agent
            if _has_concrete_task(oneshot.get("original_text") or ""):
                return plan_from_oneshot(oneshot)
            agent = oneshot["agent"]
            original = str(pending.get("original_text") or text)
            return {
                "target": "hermes" if agent == "hermes" else "coder",
                "mode": str(pending.get("mode") or "short"),
                "reason": f"clarify:oneshot:{agent}",
                "source": "clarify",
                "agent": agent,
                "original_text": original,
                "clarify_question": "",
            }
        agent = parse_agent_choice(text)
        if not agent:
            return {
                "target": "clarify",
                "mode": "short",
                "reason": "clarify:reask",
                "source": "clarify",
                "clarify_question": (
                    "没听清。请说一 Hermes、二本地、三云端；"
                    "或一次说完：用 Hermes 帮我写…"
                ),
                "agent": "",
                "original_text": pending.get("original_text") or "",
            }
        clear(session_id)
        original = str(pending.get("original_text") or text)
        mode = str(pending.get("mode") or "short")
        return {
            "target": "hermes" if agent == "hermes" else "coder",
            "mode": mode if agent == "hermes" else "short",
            "reason": f"clarify:chose:{agent}",
            "source": "clarify",
            "agent": agent,
            "original_text": original,
            "clarify_question": "",
        }
    clear(session_id)
    return None
