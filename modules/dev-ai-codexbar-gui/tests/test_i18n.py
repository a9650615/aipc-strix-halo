"""i18n: language detection + catalog wiring (static)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI))


def test_normalize_and_detect(monkeypatch) -> None:
    from codexbar_gui import i18n

    assert i18n._normalize_lang("zh_TW.UTF-8") == "zh_TW"
    assert i18n._normalize_lang("zh-CN") == "zh_CN"
    assert i18n._normalize_lang("en_US") == "en"
    assert i18n._normalize_lang("auto") == "auto"

    monkeypatch.setenv("LANG", "zh_TW.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.delenv("CODEXBAR_LANG", raising=False)
    assert i18n.detect_system_language() == "zh_TW"


def test_t_zh_tw_and_en(monkeypatch) -> None:
    from codexbar_gui.i18n import set_language, t, translate_resets_in, translate_window_label

    monkeypatch.delenv("CODEXBAR_LANG", raising=False)
    set_language("en")
    assert t("overview") == "Overview"
    assert t("session_5h") == "Session (5h)"
    assert t("percent_left", n=42) == "42% left"
    assert translate_window_label("Session (5h)") == "Session (5h)"
    assert translate_resets_in("Resets in 4h 59m") == "Resets in 4h 59m"

    set_language("zh_TW")
    assert t("overview") == "概覽"
    assert t("session_5h") == "工作階段（5 小時）"
    assert t("percent_left", n=42) == "剩餘 42%"
    assert t("pace_in_reserve", n=13) == "比預期進度少用 13%"
    assert translate_window_label("Session (5h)") == "工作階段（5 小時）"
    assert translate_window_label("Weekly") == "每週"
    assert translate_resets_in("Resets in 4h 59m") == "4h 59m 後重置"
    assert translate_resets_in("Reset due") == "已到重置時間"

    set_language("zh_CN")
    assert t("overview") == "概览"
    assert t("refresh") == "刷新"
    assert t("quit") == "退出 CodexBar"


def test_format_pace_lines_localized(monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone

    from codexbar_gui.i18n import set_language
    from codexbar_gui.upstream import compute_pace, format_pace_lines

    resets = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    pace = compute_pace(1.0, 300, resets)
    assert pace is not None

    set_language("en")
    lines = format_pace_lines(pace)
    assert lines is not None
    assert "reserve" in lines["primary"].lower() or "%" in lines["primary"]

    set_language("zh_TW")
    lines_zh = format_pace_lines(pace)
    assert lines_zh is not None
    assert "預期" in lines_zh["primary"] or "預期" in lines_zh["secondary"]


def test_resolve_prefers_env(monkeypatch) -> None:
    from codexbar_gui.i18n import resolve_language, set_language

    monkeypatch.setenv("CODEXBAR_LANG", "zh_CN")
    set_language(None)
    assert resolve_language() == "zh_CN"

    monkeypatch.setenv("CODEXBAR_LANG", "en")
    set_language(None)
    assert resolve_language() == "en"
