"""Local voice intents — fast actions without LLM tool-calling.

Voice turns that only hit supervisor chat feel empty; these keyword intents
run in aipc-voice-once (session DISPLAY/Pulse preserved) before /chat.

Never change master volume except for explicit volume intents the user spoke.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

MuteFlag = Path(os.environ.get("AIPC_VOICE_MUTE_FLAG", "/run/aipc/voice-mute"))
UserMuteFlag = Path(
    os.environ.get(
        "AIPC_VOICE_MUTE_FLAG_USER",
        str(Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "aipc-voice-mute"),
    )
)


def _norm(text: str) -> str:
    raw = (text or "").strip().lower()
    for ch in "。.!！?？,，、；;:：\"'“”‘’~～…·":
        raw = raw.replace(ch, "")
    return "".join(raw.split())


def _contains_any(n: str, words: tuple[str, ...]) -> bool:
    return any(w in n for w in words)


@dataclass(frozen=True)
class IntentHit:
    name: str
    reply: str


def matches_open_portal(text: str) -> bool:
    try:
        from aipc_lib.portal import matches_open_portal_intent

        return matches_open_portal_intent(text)
    except Exception:
        pass
    import difflib

    n = _norm(text)
    nouns = (
        "dashboard", "portal", "仪表板", "儀表板", "管理界面", "管理介面",
        "控制台", "面板", "首页", "首頁",
    )
    verbs = ("open", "show", "launch", "打开", "打開", "开启", "開啟", "显示", "顯示")
    if n in {
        "dashboard", "portal", "打开dashboard", "打開dashboard",
        "打开portal", "打開portal", "opendashboard", "openportal",
        "打开面板", "打開面板",
    }:
        return True
    has_noun = any(x in n for x in nouns)
    if not has_noun and "dash" in n and "board" in n:
        has_noun = True
    if not has_noun:
        for tok in re.findall(r"[a-z]+", n):
            if difflib.SequenceMatcher(None, tok, "dashboard").ratio() >= 0.72:
                has_noun = True
                break
            if difflib.SequenceMatcher(None, tok, "portal").ratio() >= 0.85:
                has_noun = True
                break
    has_verb = any(v in n for v in verbs)
    return bool(has_noun and (has_verb or len(n) <= 24))


def open_portal(_text: str = "") -> str:
    aipc = shutil.which("aipc")
    if aipc:
        try:
            proc = subprocess.run(
                [aipc, "portal", "open"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            out = (proc.stdout or proc.stderr or "").strip()
            if proc.returncode == 0:
                return out or "已打开 AIPC 管理面板。"
            return out or "打开 AIPC 管理面板失败。"
        except Exception as exc:  # noqa: BLE001
            return f"打开面板失败：{exc}"
    url = os.environ.get("AIPC_PORTAL_URL", "http://127.0.0.1:7080/")
    try:
        env = os.environ.copy()
        env.setdefault("DISPLAY", ":0")
        if shutil.which("xdg-open"):
            subprocess.run(["xdg-open", url], env=env, check=False, timeout=10)
        return f"已尝试打开 {url}"
    except Exception as exc:  # noqa: BLE001
        return f"打开面板失败：{exc}"


def _tz() -> ZoneInfo:
    name = os.environ.get("TZ") or "Asia/Taipei"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def intent_time(_text: str) -> str:
    now = datetime.now(_tz())
    return f"现在是{now.strftime('%-H点%M分')}。"


def intent_date(_text: str) -> str:
    now = datetime.now(_tz())
    week = "一二三四五六日"[now.weekday()]
    return f"今天是{now.strftime('%Y年%-m月%-d日')}，星期{week}。"


def intent_capabilities(_text: str) -> str:
    return (
        "我能：报时日期、开关静音、调节音量、打开面板浏览器终端、"
        "查语音状态、看桌面（说「看一下桌面」），"
        "以及用助理查日程邮件文件与用量。复杂事请说具体一点。"
    )


def _probe(url: str, timeout: float = 1.2) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def intent_voice_status(_text: str) -> str:
    stt = _probe(os.environ.get("AIPC_VOICE_STT_HEALTH", "http://127.0.0.1:9001/healthz"))
    chat = _probe(os.environ.get("AIPC_VOICE_CHAT_HEALTH", "http://127.0.0.1:4100/healthz"))
    tts = _probe(os.environ.get("AIPC_KOKORO_HEALTH", "http://127.0.0.1:8880/v1/models"))
    muted = MuteFlag.exists() or UserMuteFlag.exists()
    parts = [
        f"语音识别{'正常' if stt else '异常'}",
        f"对话{'正常' if chat else '异常'}",
        f"语音合成{'正常' if tts else '异常'}",
        "已静音" if muted else "未静音",
    ]
    return "，".join(parts) + "。"


def _launch(desktop_or_cmd: list[str]) -> bool:
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        subprocess.Popen(
            desktop_or_cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False


def intent_open_browser(_text: str) -> str:
    # Prefer Zen (default on this machine), then xdg-open https://
    if Path("/var/lib/flatpak/exports/share/applications/app.zen_browser.zen.desktop").is_file():
        if _launch(["gtk-launch", "app.zen_browser.zen"]) or _launch(
            ["flatpak", "run", "app.zen_browser.zen"]
        ):
            return "已打开浏览器。"
    for bin_name in ("firefox", "google-chrome-stable", "google-chrome", "chromium-browser", "chromium"):
        p = shutil.which(bin_name)
        if p and _launch([p]):
            return "已打开浏览器。"
    if shutil.which("xdg-open") and _launch(["xdg-open", "https://"]):
        return "已打开浏览器。"
    return "没找到可用的浏览器。"


def intent_open_terminal(_text: str) -> str:
    for bin_name in ("konsole", "kitty", "gnome-terminal", "alacritty", "xterm"):
        p = shutil.which(bin_name)
        if p and _launch([p]):
            return "已打开终端。"
    return "没找到可用的终端。"


def _set_mute(on: bool) -> str:
    # Prefer system target if available; always write user flag (wake checks both).
    if on:
        try:
            UserMuteFlag.parent.mkdir(parents=True, exist_ok=True)
            UserMuteFlag.write_text("1\n", encoding="utf-8")
        except OSError as exc:
            return f"无法写入静音标记：{exc}"
        try:
            MuteFlag.parent.mkdir(parents=True, exist_ok=True)
            MuteFlag.write_text("1\n", encoding="utf-8")
        except OSError:
            pass
        subprocess.run(
            ["systemctl", "start", "aipc-voice-mute.target"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        return "助手已静音。说取消静音可恢复。"
    try:
        UserMuteFlag.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        MuteFlag.unlink(missing_ok=True)
    except OSError:
        pass
    subprocess.run(
        ["systemctl", "stop", "aipc-voice-mute.target"],
        capture_output=True,
        check=False,
        timeout=5,
    )
    return "已取消静音。"


def intent_mute(_text: str) -> str:
    return _set_mute(True)


def intent_unmute(_text: str) -> str:
    return _set_mute(False)


def _volume_step(delta_pct: int) -> str:
    """User-spoken volume change only — not used for duck/TTS."""
    try:
        out = subprocess.check_output(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            text=True,
            timeout=3,
        )
        m = re.search(r"/\s*(\d+)%", out)
        cur = int(m.group(1)) if m else 50
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "读不到当前音量。"
    new = max(0, min(150, cur + delta_pct))
    r = subprocess.run(
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{new}%"],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    if r.returncode != 0:
        return "调节音量失败。"
    return f"音量已调到{new}%。"


def intent_volume_up(_text: str) -> str:
    return _volume_step(10)


def intent_volume_down(_text: str) -> str:
    return _volume_step(-10)


def intent_volume_maxish(_text: str) -> str:
    # Explicit user ask for loud — still cap at 100% not 150.
    r = subprocess.run(
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"],
        capture_output=True,
        timeout=3,
        check=False,
    )
    return "音量已调到100%。" if r.returncode == 0 else "调节音量失败。"


def intent_volume_mute_sink(_text: str) -> str:
    r = subprocess.run(
        ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
        capture_output=True,
        timeout=3,
        check=False,
    )
    return "系统已静音。" if r.returncode == 0 else "系统静音失败。"


def intent_volume_unmute_sink(_text: str) -> str:
    r = subprocess.run(
        ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
        capture_output=True,
        timeout=3,
        check=False,
    )
    return "系统已取消静音。" if r.returncode == 0 else "取消系统静音失败。"


# (name, matcher, handler) — first match wins
_Intent = tuple[str, Callable[[str], bool], Callable[[str], str]]


def _matchers() -> list[_Intent]:
    def m_time(n: str) -> bool:
        return _contains_any(
            n,
            ("几点", "幾點", "什么时间", "什麼時間", "现在时间", "現在時間", "what time", "current time"),
        ) or n in {"时间", "時間", "time"}

    def m_date(n: str) -> bool:
        return _contains_any(
            n,
            ("几号", "幾號", "日期", "星期几", "星期幾", "今天星期", "what day", "what date", "today's date"),
        ) or n in {"日期", "date"}

    def m_caps(n: str) -> bool:
        return _contains_any(
            n,
            (
                "你能做什么", "你會做什麼", "你会做什么", "有什么功能", "有什麼功能",
                "能干什么", "能幹什麼", "what can you do", "help me", "帮助", "幫助",
            ),
        )

    # Screen-see is handled by orchestrator /chat route (screen_see + vlm-screen);
    # do not short-circuit here so voice still TTS-speaks the VLM description.

    def m_status(n: str) -> bool:
        return _contains_any(
            n,
            (
                "语音状态", "語音狀態", "助手状态", "助理狀態", "系统状态", "系統狀態",
                "voice status", "health check", "健康检查", "健康檢查",
            ),
        )

    def m_browser(n: str) -> bool:
        if matches_open_portal(n):
            return False
        return _contains_any(
            n,
            (
                "打开浏览器", "打開瀏覽器", "开启浏览器", "開啟瀏覽器",
                "open browser", "open chrome", "open firefox", "打开chrome", "打开firefox",
                "打开zen", "打開zen",
            ),
        )

    def m_term(n: str) -> bool:
        return _contains_any(
            n,
            ("打开终端", "打開終端", "打开terminal", "open terminal", "打开konsole", "开终端"),
        )

    def m_mute(n: str) -> bool:
        if _contains_any(n, ("取消静音", "取消靜音", "解除静音", "unmute")):
            return False
        return _contains_any(
            n,
            ("静音助手", "靜音助手", "助手静音", "语音静音", "語音靜音", "mute assistant", "闭嘴", "閉嘴"),
        ) or n in {"静音", "靜音", "mute"}

    def m_unmute(n: str) -> bool:
        return _contains_any(
            n,
            ("取消静音", "取消靜音", "解除静音", "打开麦克风监听", "unmute", "恢复监听", "恢復監聽"),
        )

    def m_vol_up(n: str) -> bool:
        return _contains_any(
            n,
            ("调大音量", "調大音量", "音量调大", "音量大一点", "音量大一點", "增大音量", "volume up", "louder"),
        )

    def m_vol_down(n: str) -> bool:
        return _contains_any(
            n,
            ("调小音量", "調小音量", "音量调小", "音量小一点", "音量小一點", "减小音量", "volume down", "quieter"),
        )

    def m_vol_max(n: str) -> bool:
        return _contains_any(n, ("音量最大", "最大音量", "volume max", "full volume"))

    def m_sys_mute(n: str) -> bool:
        return _contains_any(n, ("系统静音", "系統靜音", "喇叭静音", "mute system", "mute speakers"))

    def m_sys_unmute(n: str) -> bool:
        return _contains_any(n, ("取消系统静音", "取消系統靜音", "打开喇叭", "unmute system"))

    def m_portal(n: str) -> bool:
        return matches_open_portal(n)

    return [
        ("capabilities", lambda t: m_caps(_norm(t)), intent_capabilities),
        ("time", lambda t: m_time(_norm(t)), intent_time),
        ("date", lambda t: m_date(_norm(t)), intent_date),
        ("voice_status", lambda t: m_status(_norm(t)), intent_voice_status),
        ("unmute", lambda t: m_unmute(_norm(t)), intent_unmute),
        ("mute", lambda t: m_mute(_norm(t)), intent_mute),
        ("volume_up", lambda t: m_vol_up(_norm(t)), intent_volume_up),
        ("volume_down", lambda t: m_vol_down(_norm(t)), intent_volume_down),
        ("volume_max", lambda t: m_vol_max(_norm(t)), intent_volume_maxish),
        ("system_mute", lambda t: m_sys_mute(_norm(t)), intent_volume_mute_sink),
        ("system_unmute", lambda t: m_sys_unmute(_norm(t)), intent_volume_unmute_sink),
        ("open_portal", lambda t: m_portal(t), open_portal),
        ("open_browser", lambda t: m_browser(_norm(t)), intent_open_browser),
        ("open_terminal", lambda t: m_term(_norm(t)), intent_open_terminal),
    ]


def resolve_intent(text: str) -> IntentHit | None:
    for name, match, handler in _matchers():
        try:
            if match(text):
                return IntentHit(name=name, reply=handler(text))
        except Exception as exc:  # noqa: BLE001
            return IntentHit(name=name, reply=f"执行{name}失败：{exc}")
    return None


def self_test() -> None:
    assert resolve_intent("现在几点了") and resolve_intent("现在几点了").name == "time"
    assert resolve_intent("今天几号") and resolve_intent("今天几号").name == "date"
    assert resolve_intent("打开面板") and resolve_intent("打开面板").name == "open_portal"
    assert resolve_intent("打开浏览器") and resolve_intent("打开浏览器").name == "open_browser"
    assert resolve_intent("你能做什么") and resolve_intent("你能做什么").name == "capabilities"
    assert resolve_intent("今天天气如何") is None
    print("voice_intents: self-test OK")


if __name__ == "__main__":
    self_test()
