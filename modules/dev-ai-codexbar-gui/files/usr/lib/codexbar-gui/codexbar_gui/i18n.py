"""Lightweight i18n for CodexBar GUI — English + Chinese (zh-TW / zh-CN).

Locale resolution order:
  1. CODEXBAR_LANG env (en | zh | zh_TW | zh_CN | zh-TW | zh-CN)
  2. config.json gui.language
  3. system LANG / LC_ALL / LANGUAGE
  4. en

Usage: ``from codexbar_gui.i18n import t, set_language, current_language``
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------

_EN: Dict[str, str] = {
    # Tabs / chrome
    "overview": "Overview",
    "refresh": "Refresh",
    "usage_dashboard": "Usage Dashboard",
    "settings": "Settings...",
    "close_panel": "Close panel",
    "close_panel_tip": "Hide this panel; tray keeps running",
    "quit": "Quit CodexBar",
    "quit_tip": "Stop tray icon, web UI, and exit completely",
    "loading": "Loading...",
    "loading_providers": "Loading providers...",
    "refreshing": "refreshing...",
    "ready": "Ready",
    "providers_count": "{ok}/{n} providers",
    "providers_cli": "{ok}/{n} providers · official CLI",
    "web_not_running": "Web UI not running",
    "no_usage": "No usage data",
    "install_cli": "Install official codexbar CLI.",
    "cli_path": "CLI: {path}",
    "unavailable": "Unavailable",
    "couldnt_load": "Couldn't load usage",
    "credits": "CREDITS",
    "credits_left": "{n} left",
    "today": "Today",
    "last_n_days": "Last {n} days",
    "tokens": "{n} tokens",
    "session_5h": "Session (5h)",
    "weekly": "Weekly",
    "session": "Session",
    "percent_left": "{n}% left",
    "percent_used": "{n}% used",
    "empty": "Empty",
    "reset_due": "Reset due",
    "status_refreshing": "{base} · refreshing...",
    "err_timeout": (
        "Timed out talking to the provider CLI. Try Refresh, or set Usage source in Settings."
    ),
    "err_not_configured": "Not configured — open Settings and complete OAuth / API key.",
    "lang_applied": "Language updated. Re-open the usage panel to refresh all labels.",
    # Pace (official)
    "pace_in_reserve": "{n}% in reserve",
    "pace_in_deficit": "{n}% in deficit",
    "pace_on_pace": "On pace",
    "pace_slower": "Slower than expected · expected {exp}% used by now",
    "pace_faster": "Faster than expected · expected {exp}% used by now",
    "pace_matching": "Matching expected burn · ~{exp}% of window elapsed",
    "lasts_until_reset": "Lasts until reset",
    "may_run_out_early": "May run out early",
    "runs_out_in": "Runs out in ~{eta}",
    "watch_usage": "Watch usage",
    # Settings
    "settings_title": "CodexBar Settings",
    "settings_heading": "Settings · Display + Providers",
    "settings_hint": (
        "Same file as official CodexBar: {path}. "
        "Display section mirrors macOS Display prefs (merged tray on Linux). "
        "OAuth only for Codex / Claude / Gemini; Grok = web/API; GLM = zai."
    ),
    "menu_bar_display": "Menu bar · Display",
    "menu_bar_note": (
        "Linux uses one merged tray icon (official Merge Icons). "
        "Choose which provider drives the bars, remaining vs used fill, and Overview order."
    ),
    "tray_provider": "Tray provider",
    "pinned_id": "Pinned id",
    "bar_fill": "Bar fill",
    "icon_style": "Icon style",
    "overview_providers": "Overview providers",
    "overview_placeholder": "Overview order, e.g. codex,claude,zai  (empty = all enabled)",
    "show_percent_tooltip": "Show percent in tray tooltip",
    "refresh_interval": "Refresh interval",
    "providers": "Providers",
    "show_all_providers": "Show all providers (full catalog)",
    "reload_disk": "Reload from disk",
    "open_config_dir": "Open config dir",
    "save": "Save",
    "cancel": "Cancel",
    "usage_source": "Usage source",
    "cookie_source": "Cookie source",
    "api_key": "API key",
    "cookie_header": "Cookie header",
    "login_oauth": "Login (OAuth)…",
    "logging_in": "Logging in…",
    "oauth_running": "OAuth login running (browser may open)…",
    "refresh_status": "Refresh status",
    "language": "Language",
    "lang_auto": "System default",
    "lang_en": "English",
    "lang_zh_tw": "繁體中文",
    "lang_zh_cn": "简体中文",
    "sel_highest": "Highest usage (lowest % left)",
    "sel_first": "First enabled (config order)",
    "sel_pinned": "Pinned provider",
    "show_remaining": "Show remaining % (default)",
    "show_used": "Show used %",
    "icon_dual": "Dual bars (session + weekly)",
    "icon_primary": "Primary bar only",
    "icon_brand": "Single brand bar",
    "saved_settings": "Menu bar display + providers updated.\nTray icon refreshes on the next poll (or click Refresh).",
    "settings_saved": "Settings",
    "error": "Error",
    "failed_save": "Failed to save: {err}",
    "showing_featured": "Showing featured + enabled ({n}). Full catalog on disk: {total} — tick “Show all providers”.",
    "seconds_suffix": " s",
    # Tray
    "tray_tip": "CodexBar — click for usage",
    "tray_click": "(click tray icon)",
    "tray_timeout": "CLI timeout/empty — click for details",
    # Time-ish (resets)
    "resets_in": "Resets in {t}",
    "updated_just_now": "Updated just now",
    "updated_m_ago": "Updated {n}m ago",
    "updated_h_ago": "Updated {n}h ago",
    "updated_d_ago": "Updated {n}d ago",
}

_ZH_TW: Dict[str, str] = {
    "overview": "概覽",
    "refresh": "重新整理",
    "usage_dashboard": "用量儀表板",
    "settings": "設定…",
    "close_panel": "關閉面板",
    "close_panel_tip": "只關閉此面板，系統匣繼續執行",
    "quit": "結束 CodexBar",
    "quit_tip": "停止系統匣圖示、網頁介面並完全結束",
    "loading": "載入中…",
    "loading_providers": "正在載入供應商…",
    "refreshing": "更新中…",
    "ready": "就緒",
    "providers_count": "{ok}/{n} 個供應商",
    "providers_cli": "{ok}/{n} 個供應商 · 官方 CLI",
    "web_not_running": "網頁介面未執行",
    "no_usage": "沒有用量資料",
    "install_cli": "請安裝官方 codexbar CLI。",
    "cli_path": "CLI：{path}",
    "unavailable": "無法使用",
    "couldnt_load": "無法載入用量",
    "credits": "點數",
    "credits_left": "剩餘 {n}",
    "today": "今天",
    "last_n_days": "近 {n} 天",
    "tokens": "{n} tokens",
    "session_5h": "工作階段（5 小時）",
    "weekly": "每週",
    "session": "工作階段",
    "percent_left": "剩餘 {n}%",
    "percent_used": "已用 {n}%",
    "empty": "無資料",
    "reset_due": "已到重置時間",
    "status_refreshing": "{base} · 更新中…",
    "err_timeout": "與供應商 CLI 通訊逾時。請按「重新整理」，或到設定調整用量來源。",
    "err_not_configured": "尚未設定 — 請開啟設定完成 OAuth 或 API 金鑰。",
    "lang_applied": "語言已更新。請重新開啟用量面板以套用全部標籤。",
    "pace_in_reserve": "比預期進度少用 {n}%",
    "pace_in_deficit": "比預期進度多用 {n}%",
    "pace_on_pace": "符合預期進度",
    "pace_slower": "使用速度低於預期 · 目前預期應已用 {exp}%",
    "pace_faster": "使用速度快於預期 · 目前預期應已用 {exp}%",
    "pace_matching": "貼近預期消耗 · 時窗約已過 {exp}%",
    "lasts_until_reset": "可撐到重置",
    "may_run_out_early": "可能提早用完",
    "runs_out_in": "約 {eta} 後用完",
    "watch_usage": "請留意用量",
    "settings_title": "CodexBar 設定",
    "settings_heading": "設定 · 顯示與供應商",
    "settings_hint": (
        "設定檔與官方 CodexBar 相同：{path}。"
        "顯示區對應 macOS Display（Linux 為合併系統匣圖示）。"
        "OAuth 僅 Codex / Claude / Gemini；Grok = 網頁/API；GLM = zai。"
    ),
    "menu_bar_display": "選單列 · 顯示",
    "menu_bar_note": (
        "Linux 使用單一合併系統匣圖示（對應官方 Merge Icons）。"
        "可選擇驅動進度條的供應商、顯示剩餘或已用、以及概覽順序。"
    ),
    "tray_provider": "系統匣供應商",
    "pinned_id": "固定供應商 id",
    "bar_fill": "進度條填色",
    "icon_style": "圖示樣式",
    "overview_providers": "概覽供應商",
    "overview_placeholder": "概覽順序，例如 codex,claude,zai（空白 = 全部已啟用）",
    "show_percent_tooltip": "在系統匣提示顯示百分比",
    "refresh_interval": "重新整理間隔",
    "providers": "供應商",
    "show_all_providers": "顯示全部供應商",
    "reload_disk": "從磁碟重新載入",
    "open_config_dir": "開啟設定目錄",
    "save": "儲存",
    "cancel": "取消",
    "usage_source": "用量來源",
    "cookie_source": "Cookie 來源",
    "api_key": "API 金鑰",
    "cookie_header": "Cookie 標頭",
    "login_oauth": "登入（OAuth）…",
    "logging_in": "登入中…",
    "oauth_running": "正在進行 OAuth 登入（可能開啟瀏覽器）…",
    "refresh_status": "重新整理狀態",
    "language": "語言",
    "lang_auto": "跟隨系統",
    "lang_en": "English",
    "lang_zh_tw": "繁體中文",
    "lang_zh_cn": "简体中文",
    "sel_highest": "用量最高（剩餘 % 最低）",
    "sel_first": "第一個已啟用（設定順序）",
    "sel_pinned": "固定供應商",
    "show_remaining": "顯示剩餘 %（預設）",
    "show_used": "顯示已用 %",
    "icon_dual": "雙條（工作階段 + 每週）",
    "icon_primary": "僅主進度條",
    "icon_brand": "單一品牌條",
    "saved_settings": "已更新選單列顯示與供應商。\n系統匣圖示會在下次輪詢或按「重新整理」後更新。",
    "settings_saved": "設定",
    "error": "錯誤",
    "failed_save": "儲存失敗：{err}",
    "showing_featured": "顯示精選與已啟用（{n}）。磁碟上共 {total} 個 — 勾選「顯示全部供應商」。",
    "seconds_suffix": " 秒",
    "tray_tip": "CodexBar — 點一下查看用量",
    "tray_click": "（點系統匣圖示）",
    "tray_timeout": "CLI 逾時或無資料 — 點一下查看詳情",
    "resets_in": "{t} 後重置",
    "updated_just_now": "剛剛更新",
    "updated_m_ago": "{n} 分鐘前更新",
    "updated_h_ago": "{n} 小時前更新",
    "updated_d_ago": "{n} 天前更新",
}

# Simplified Chinese (subset differences; fall back to zh_TW then en)
_ZH_CN: Dict[str, str] = {
    **_ZH_TW,
    "overview": "概览",
    "refresh": "刷新",
    "usage_dashboard": "用量仪表板",
    "settings": "设置…",
    "close_panel": "关闭面板",
    "close_panel_tip": "仅关闭此面板，托盘继续运行",
    "quit": "退出 CodexBar",
    "quit_tip": "停止托盘图标、网页界面并完全退出",
    "loading": "加载中…",
    "loading_providers": "正在加载供应商…",
    "refreshing": "更新中…",
    "ready": "就绪",
    "providers_count": "{ok}/{n} 个供应商",
    "providers_cli": "{ok}/{n} 个供应商 · 官方 CLI",
    "web_not_running": "网页界面未运行",
    "no_usage": "没有用量数据",
    "install_cli": "请安装官方 codexbar CLI。",
    "unavailable": "不可用",
    "couldnt_load": "无法加载用量",
    "credits": "点数",
    "credits_left": "剩余 {n}",
    "today": "今天",
    "last_n_days": "近 {n} 天",
    "session_5h": "会话（5 小时）",
    "weekly": "每周",
    "session": "会话",
    "percent_left": "剩余 {n}%",
    "percent_used": "已用 {n}%",
    "empty": "无数据",
    "reset_due": "已到重置时间",
    "status_refreshing": "{base} · 更新中…",
    "err_timeout": "与供应商 CLI 通讯超时。请点“刷新”，或到设置调整用量来源。",
    "err_not_configured": "尚未配置 — 请打开设置完成 OAuth 或 API 密钥。",
    "lang_applied": "语言已更新。请重新打开用量面板以套用全部标签。",
    "pace_in_reserve": "比预期进度少用 {n}%",
    "pace_in_deficit": "比预期进度多用 {n}%",
    "pace_on_pace": "符合预期进度",
    "pace_slower": "使用速度低于预期 · 目前预期应已用 {exp}%",
    "pace_faster": "使用速度快于预期 · 目前预期应已用 {exp}%",
    "pace_matching": "贴近预期消耗 · 时窗约已过 {exp}%",
    "lasts_until_reset": "可撑到重置",
    "may_run_out_early": "可能提早用完",
    "runs_out_in": "约 {eta} 后用完",
    "watch_usage": "请留意用量",
    "settings_title": "CodexBar 设置",
    "settings_heading": "设置 · 显示与供应商",
    "menu_bar_display": "菜单栏 · 显示",
    "tray_provider": "托盘供应商",
    "pinned_id": "固定供应商 id",
    "bar_fill": "进度条填色",
    "icon_style": "图标样式",
    "overview_providers": "概览供应商",
    "overview_placeholder": "概览顺序，例如 codex,claude,zai（空白 = 全部已启用）",
    "show_percent_tooltip": "在托盘提示显示百分比",
    "refresh_interval": "刷新间隔",
    "providers": "供应商",
    "show_all_providers": "显示全部供应商",
    "reload_disk": "从磁盘重新加载",
    "open_config_dir": "打开设置目录",
    "save": "保存",
    "cancel": "取消",
    "usage_source": "用量来源",
    "cookie_source": "Cookie 来源",
    "api_key": "API 密钥",
    "login_oauth": "登录（OAuth）…",
    "logging_in": "登录中…",
    "oauth_running": "正在进行 OAuth 登录（可能打开浏览器）…",
    "refresh_status": "刷新状态",
    "language": "语言",
    "lang_auto": "跟随系统",
    "sel_highest": "用量最高（剩余 % 最低）",
    "sel_first": "第一个已启用（设置顺序）",
    "sel_pinned": "固定供应商",
    "show_remaining": "显示剩余 %（默认）",
    "show_used": "显示已用 %",
    "icon_dual": "双条（会话 + 每周）",
    "icon_primary": "仅主进度条",
    "icon_brand": "单一品牌条",
    "saved_settings": "已更新菜单栏显示与供应商。\n托盘图标会在下次轮询或点“刷新”后更新。",
    "settings_saved": "设置",
    "error": "错误",
    "failed_save": "保存失败：{err}",
    "showing_featured": "显示精选与已启用（{n}）。磁盘上共 {total} 个 — 勾选“显示全部供应商”。",
    "seconds_suffix": " 秒",
    "tray_tip": "CodexBar — 点击查看用量",
    "tray_click": "（点击托盘图标）",
    "tray_timeout": "CLI 超时或无数据 — 点击查看详情",
    "resets_in": "{t} 后重置",
    "updated_just_now": "刚刚更新",
    "updated_m_ago": "{n} 分钟前更新",
    "updated_h_ago": "{n} 小时前更新",
    "updated_d_ago": "{n} 天前更新",
}

_CATALOGS: Dict[str, Dict[str, str]] = {
    "en": _EN,
    "zh_TW": _ZH_TW,
    "zh_CN": _ZH_CN,
}

_current: str = "en"
_override: Optional[str] = None  # from config/env, "auto" or lang code


def _normalize_lang(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip().replace("-", "_")
    if not s or s.lower() in {"auto", "system", "default"}:
        return "auto"
    low = s.lower()
    if low in {"en", "en_us", "en_gb"}:
        return "en"
    if low in {"zh_tw", "zh_hk", "zh_mo", "zh_hant"}:
        return "zh_TW"
    if low in {"zh_cn", "zh_sg", "zh_hans", "zh"}:
        # bare "zh" → Traditional on this machine's audience default TW; map zh alone to zh_TW if LANG says TW
        if low == "zh":
            return "zh_CN"
        return "zh_CN"
    if low.startswith("zh_tw") or low.startswith("zh_hk"):
        return "zh_TW"
    if low.startswith("zh"):
        return "zh_CN"
    if low.startswith("en"):
        return "en"
    return None


def detect_system_language() -> str:
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(key) or ""
        if key == "LANGUAGE" and val:
            val = val.split(":")[0]
        code = _normalize_lang(val.split(".")[0] if val else None)
        if code and code != "auto":
            return code
    return "en"


def _read_config_language() -> Optional[str]:
    for path in (
        Path.home() / ".config" / "codexbar" / "config.json",
        Path.home() / ".codexbar" / "config.json",
    ):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        gui = data.get("gui") if isinstance(data.get("gui"), dict) else {}
        return _normalize_lang(str(gui.get("language") or "") or None)
    return None


def resolve_language(preferred: Optional[str] = None) -> str:
    """Resolve effective language code: en | zh_TW | zh_CN."""
    for cand in (
        preferred,
        _normalize_lang(os.environ.get("CODEXBAR_LANG")),
        _read_config_language(),
    ):
        if cand == "auto" or cand is None:
            continue
        if cand in _CATALOGS:
            return cand
    # auto / missing
    env = _normalize_lang(os.environ.get("CODEXBAR_LANG"))
    if env == "auto" or env is None:
        # Prefer Traditional when system is zh_TW (this machine)
        sys_lang = detect_system_language()
        return sys_lang if sys_lang in _CATALOGS else "en"
    return env if env in _CATALOGS else "en"


def set_language(lang: Optional[str]) -> str:
    """Set language override (None/auto = follow system/config). Returns effective."""
    global _current, _override
    _override = _normalize_lang(lang) if lang else None
    if _override and _override != "auto" and _override in _CATALOGS:
        _current = _override
    else:
        _current = resolve_language("auto" if _override == "auto" else None)
    return _current


def init_language() -> str:
    """Call once at app start."""
    return set_language(None)


def current_language() -> str:
    return _current


def t(key: str, **kwargs: Any) -> str:
    """Translate key; missing keys fall back to English then the key itself."""
    cat = _CATALOGS.get(_current) or _EN
    text = cat.get(key) or _EN.get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def translate_window_label(label: str) -> str:
    """Map Session/Weekly labels to locale."""
    low = (label or "").lower()
    if "5h" in low or low in {"session", "session (5h)", "primary"}:
        return t("session_5h")
    if "week" in low or low in {"weekly", "secondary"}:
        return t("weekly")
    return label


def translate_resets_in(text: str) -> str:
    """Best-effort localization of reset countdown strings from CLI."""
    if not text:
        return text
    # Already Chinese-ish
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    if not _current.startswith("zh"):
        return text
    low = text.strip().lower()
    if low in {"reset due", "resets due"}:
        return t("reset_due")
    # "Resets in 4h 59m" / "Resets in 15m"
    m = re.match(r"(?i)resets?\s+in\s+(.+)$", text.strip())
    if m:
        return t("resets_in", t=m.group(1).strip())
    return text


def translate_updated_label(text: str) -> str:
    """Localize English updated-ago lines from the data layer."""
    if not text or not _current.startswith("zh"):
        return text
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    s = text.strip()
    if re.match(r"(?i)updated\s+just\s+now", s):
        return t("updated_just_now")
    m = re.match(r"(?i)updated\s+(\d+)m\s+ago", s)
    if m:
        return t("updated_m_ago", n=m.group(1))
    m = re.match(r"(?i)updated\s+(\d+)h\s+ago", s)
    if m:
        return t("updated_h_ago", n=m.group(1))
    m = re.match(r"(?i)updated\s+(\d+)d\s+ago", s)
    if m:
        return t("updated_d_ago", n=m.group(1))
    return text
