"""STT slip repair before intent / agent routing.

One wrong character often kills keyword match (写代码→写代买, Hermes→赫尔墨斯).
We repair *routing-critical* tokens with:
  1) known homophone / STT mangling table
  2) fuzzy match against a small lexicon (difflib)

Does NOT rewrite free-form content aggressively — only patches known slots
so 提示词+任务 / agent names / tool intents still land.
"""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Iterable

# (wrong_or_variant, correct) — longer wrong forms first when applied
_LITERAL_FIXES: tuple[tuple[str, str], ...] = (
    # wake / assistant names
    ("嘿嘴理", "嘿助理"),
    ("嘿嘴", "嘿助理"),
    ("嘿助哩", "嘿助理"),
    ("嘿自理", "嘿助理"),
    ("嗨助理", "嘿助理"),
    ("黑助理", "嘿助理"),
    ("小飞幕", "小廢物"),
    ("小飛幕", "小廢物"),
    ("小飞物", "小廢物"),
    ("小废物", "小廢物"),
    # agents
    ("赫尔墨斯", "hermes"),
    ("赫爾墨斯", "hermes"),
    ("赫米斯", "hermes"),
    ("her mes", "hermes"),
    ("hernes", "hermes"),
    ("hermas", "hermes"),
    ("herms", "hermes"),
    ("coder agentic", "coder-agentic"),
    ("coderagentic", "coder-agentic"),
    ("coder cloud", "coder-cloud"),
    ("codercloud", "coder-cloud"),
    ("本地编码", "本地编码"),
    ("本地編碼", "本地编码"),
    # coding intents (common STT slips)
    ("写代买", "写代码"),
    ("寫代買", "写代码"),
    ("写带码", "写代码"),
    ("写代码吗", "写代码"),
    ("改代买", "改代码"),
    ("修吧g", "修bug"),
    ("修吧G", "修bug"),
    ("修吧个", "修bug"),
    ("得bug", "debug"),
    ("得吧g", "debug"),
    # tools / daily
    ("用两", "用量"),
    ("用兩", "用量"),
    ("用亮", "用量"),
    ("用了吗", "用量"),
    ("额渡", "额度"),
    ("額渡", "额度"),
    ("日厉", "日历"),
    ("日曆", "日历"),
    ("日立", "日历"),
    ("会意", "会议"),
    ("搜一下下", "搜一下"),
    ("搜索一下", "搜索"),
    # prompt+task markers
    ("提示词", "提示词"),
    ("提示詞", "提示词"),
    ("提示次", "提示词"),
    ("提示池", "提示词"),
    ("提式词", "提示词"),
    ("任物", "任务"),
    ("任 务", "任务"),
    ("任 務", "任务"),
)

# Lexicon for fuzzy window match (routing-critical only)
_LEXICON: tuple[str, ...] = (
    "嘿助理",
    "你好助理",
    "小廢物",
    "hermes",
    "coder-agentic",
    "coder-cloud",
    "写代码",
    "改代码",
    "debug",
    "修bug",
    "实现",
    "重构",
    "用量",
    "额度",
    "日历",
    "会议",
    "搜一下",
    "搜索",
    "提示词",
    "任务",
    "后台",
    "慢慢做",
    "完整实现",
)


def _enabled() -> bool:
    return os.environ.get("AIPC_STT_REPAIR", "1") not in ("0", "false", "no", "off")


def _fuzzy_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance; only for short STT windows."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # two-row DP
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _near_term(span: str, term: str, *, max_ed: int) -> bool:
    """True if span is a 1-ish char STT slip of term — not a bare substring expand."""
    if not span or not term or span == term:
        return False
    # "代码" ⊂ "改代码" would wrongly expand via ratio alone — refuse pure substrings
    if span in term or term in span:
        return False
    if abs(len(span) - len(term)) > max_ed:
        return False
    return _edit_distance(span.lower(), term.lower()) <= max_ed


def _apply_literals(text: str) -> str:
    out = text
    # longest wrong first
    for wrong, right in sorted(_LITERAL_FIXES, key=lambda x: len(x[0]), reverse=True):
        if wrong and wrong in out and wrong != right:
            out = out.replace(wrong, right)
    # case-insensitive latin fixes
    low = out.lower()
    for wrong, right in _LITERAL_FIXES:
        if not re.search(r"[a-z]", wrong, re.I):
            continue
        w = wrong.lower()
        if w in low and wrong != right:
            out = re.sub(re.escape(wrong), right, out, flags=re.I)
            low = out.lower()
    return out


def _fuzzy_patch_lexicon(text: str, *, min_ratio: float = 0.72) -> str:
    """Replace windows that are almost a lexicon term (1-char STT slips).

    Prefer same-length substitution. Length ±1 only when edit distance is 1
    and neither side is a pure substring of the other (avoids 代码→改代码).
    """
    if not text:
        return text
    out = text
    for term in sorted(_LEXICON, key=len, reverse=True):
        n = len(term)
        if n < 2:
            continue
        # Exact already present — do not re-touch
        if term in out or term.lower() in out.lower():
            continue
        best_i, best_score, best_span = -1, -1.0, ""
        # same length first, then ±1
        for win_len in (n, max(2, n - 1), n + 1):
            if win_len > len(out):
                continue
            max_ed = 1 if n <= 6 else 2
            for i in range(0, len(out) - win_len + 1):
                span = out[i : i + win_len]
                if not re.search(r"[\w\u4e00-\u9fff]", span):
                    continue
                if not _near_term(span, term, max_ed=max_ed):
                    continue
                r = _fuzzy_ratio(span.lower(), term.lower())
                # Prefer higher ratio; tie-break same length
                score = r + (0.05 if win_len == n else 0.0)
                if score > best_score:
                    best_score, best_i, best_span = score, i, span
        if best_i >= 0 and best_score >= min_ratio and best_span != term:
            out = out[:best_i] + term + out[best_i + len(best_span) :]
    return out


def repair(text: str, *, fuzzy: bool | None = None) -> dict[str, str]:
    """Return {text, raw, notes}. ``text`` is routing-safe repaired transcript."""
    raw = (text or "").strip()
    if not raw or not _enabled():
        return {"text": raw, "raw": raw, "notes": ""}
    try:
        min_ratio = float(os.environ.get("AIPC_STT_REPAIR_RATIO", "0.72"))
    except ValueError:
        min_ratio = 0.72
    if fuzzy is None:
        fuzzy = os.environ.get("AIPC_STT_REPAIR_FUZZY", "1") not in (
            "0",
            "false",
            "no",
        )

    fixed = _apply_literals(raw)
    notes: list[str] = []
    if fixed != raw:
        notes.append("literal")
    if fuzzy:
        fuzzy_fixed = _fuzzy_patch_lexicon(fixed, min_ratio=min_ratio)
        if fuzzy_fixed != fixed:
            notes.append("fuzzy")
            fixed = fuzzy_fixed
    return {
        "text": fixed,
        "raw": raw,
        "notes": "+".join(notes),
    }


def repair_text(text: str) -> str:
    return repair(text)["text"]


def self_test() -> None:
    assert repair_text("帮我写代买") == "帮我写代码"
    # must NOT expand 代码 → 改代码 after a good literal fix
    assert "改代码" not in repair_text("帮我写代买")
    assert "写代码" in repair_text("帮我写带码")
    assert "hermes" in repair_text("用赫尔墨斯帮我写排序").lower()
    assert "hermes" in repair_text("用 hermas 写脚本").lower()
    assert "用量" in repair_text("查一下用两")
    assert "提示词" in repair_text("提式词：简洁。任务：测试")
    # free-form content should stay intact when no lexicon near-miss
    assert repair_text("今天天气如何") == "今天天气如何"
    r = repair("帮我写代买实现排序")
    assert "写代码" in r["text"] and r["text"] != r["raw"]
    print("transcript_repair self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    q = " ".join(a for a in sys.argv[1:] if a != "--self-test")
    print(repair(q))
