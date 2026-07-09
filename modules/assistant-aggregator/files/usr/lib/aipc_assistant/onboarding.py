"""First-run UX: diagnose setup gaps and run a guided wizard."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aipc_assistant.backends.online import load_online_backend
from aipc_assistant.paths import etc_dir
from aipc_assistant.slots import mode as mode_slot


@dataclass
class Check:
    id: str
    ok: bool
    title: str
    detail: str = ""
    fix_hint: str = ""
    required_for_online: bool = False


@dataclass
class SetupReport:
    ready_local: bool
    ready_online: bool
    first_run: bool
    checks: list[Check] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def _marker_path() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME", "").strip()
    if xdg:
        base = Path(xdg) / "aipc-assistant"
    else:
        base = Path.home() / ".local" / "state" / "aipc-assistant"
    return base / "onboarding_done"


def is_first_run() -> bool:
    return not _marker_path().is_file()


def mark_onboarding_done() -> Path:
    p = _marker_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("ok\n", encoding="utf-8")
    return p


def _chat_local_ok() -> tuple[bool, str]:
    """NPU-first: prefer LiteLLM resident-small; agent :4100 is optional upgrade."""
    try:
        from aipc_assistant.backends.local import npu_reachable

        ok, detail = npu_reachable()
        if ok:
            return True, f"NPU path: {detail}"
        npu_detail = detail
    except Exception as exc:  # noqa: BLE001
        npu_detail = str(exc)

    url = os.environ.get("AIPC_VOICE_CHAT_URL", "http://127.0.0.1:4100/chat")
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"text": "ping", "session_id": "onboard"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                return True, f"agent :4100 reachable (NPU was: {npu_detail})"
            return False, f"NPU unavailable ({npu_detail}); agent HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001
        return False, f"NPU unavailable ({npu_detail}); agent: {exc}"


def diagnose() -> SetupReport:
    checks: list[Check] = []
    mode = mode_slot.get_mode()
    checks.append(
        Check(
            id="mode",
            ok=True,
            title="助理模式",
            detail=f"目前：{mode}（local=本機，online=ChatGPT 訂閱）",
        )
    )

    etc = etc_dir()
    checks.append(
        Check(
            id="config",
            ok=etc.is_dir() and (etc / "mode").exists(),
            title="設定目錄",
            detail=str(etc),
            fix_hint="確認 modules/assistant-aggregator 已安裝或設定 AIPC_ASSISTANT_ETC",
        )
    )

    local_ok, local_detail = _chat_local_ok()
    checks.append(
        Check(
            id="local_backend",
            ok=local_ok,
            title="本機對話（預設 NPU resident-small）",
            detail=local_detail,
            fix_hint="啟動 litellm + lemonade，確認 /v1/models 有 resident-small（不必載入 35B）",
            required_for_online=False,
        )
    )

    online = load_online_backend()
    online_avail = online.available()
    checks.append(
        Check(
            id="playwright",
            ok=online_avail,
            title="Playwright / Chromium 引擎",
            detail="可用" if online_avail else "未安裝或 backend 不可用",
            fix_hint="pip install playwright && python3 -m playwright install chromium",
            required_for_online=True,
        )
    )

    st = online.status() if online_avail else {}
    logged_in = st.get("logged_in")
    # Try live auth if possible without long hang
    if online_avail and logged_in is None and hasattr(online, "auth_status"):
        try:
            logged_in = online.auth_status().get("logged_in")  # type: ignore[attr-defined]
        except Exception:
            logged_in = None

    storage_ok = bool(st.get("storage_state_present"))
    checks.append(
        Check(
            id="login",
            ok=logged_in is True,
            title="ChatGPT 登入狀態",
            detail=(
                "已登入"
                if logged_in is True
                else (
                    "未登入或尚無法判斷"
                    if logged_in is not True
                    else "未知"
                )
            )
            + (f"；storage_state={'有' if storage_ok else '無'}" if online_avail else ""),
            fix_hint="執行：aipc-assistant setup --online   或   aipc-chatgpt auth login",
            required_for_online=True,
        )
    )

    ready_local = local_ok
    ready_online = online_avail and logged_in is True
    first = is_first_run()

    next_steps: list[str] = []
    if first:
        next_steps.append("這是第一次使用：建議跑「aipc-assistant setup」完成引導。")
    if not local_ok:
        next_steps.append(
            "先修好 NPU 路徑：litellm + lemonade resident-small（預設不必開 agent :4100）。"
        )
    if not online_avail:
        next_steps.append("要上網：安裝 Playwright Chromium（setup 可代勞）。")
    if online_avail and logged_in is not True:
        next_steps.append("要上網：完成一次 ChatGPT 登入（setup --online 會開窗等你登）。")
    if ready_local and not ready_online:
        next_steps.append("本機已可用：aipc-assistant --text \"你好\"")
    if ready_online:
        next_steps.append("網上已就緒：aipc-assistant mode online && aipc-assistant --text \"hi\"")

    return SetupReport(
        ready_local=ready_local,
        ready_online=ready_online,
        first_run=first,
        checks=checks,
        next_steps=next_steps,
    )


def format_report(report: SetupReport, *, lang: str = "zh") -> str:
    lines = []
    lines.append("══════════════════════════════════════")
    lines.append("  aipc 助理 · 設定檢查")
    lines.append("══════════════════════════════════════")
    if report.first_run:
        lines.append("  ★ 首次使用：完成下面步驟後體驗最好")
    lines.append("")
    for c in report.checks:
        mark = "✓" if c.ok else "○"
        lines.append(f"  {mark}  {c.title}")
        if c.detail:
            lines.append(f"      {c.detail}")
        if not c.ok and c.fix_hint:
            lines.append(f"      → {c.fix_hint}")
    lines.append("")
    lines.append(
        f"  本機就緒：{'是' if report.ready_local else '否'}   "
        f"網上就緒：{'是' if report.ready_online else '否'}"
    )
    if report.next_steps:
        lines.append("")
        lines.append("  下一步：")
        for i, s in enumerate(report.next_steps, 1):
            lines.append(f"    {i}. {s}")
    lines.append("══════════════════════════════════════")
    return "\n".join(lines)


def _notify(msg: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "AIPC 助理設定", msg], check=False)
    print(msg, file=sys.stderr)


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, **kwargs)


def run_wizard(
    *,
    online: bool = False,
    skip_login: bool = False,
    non_interactive: bool = False,
    site_id: str | None = None,
) -> int:
    """Guided first-run. Config + optional LLM plan for multi-site engine."""
    print(format_report(diagnose()))
    print()

    # Multi-site plan from sites.yaml (+ local LLM if available)
    plan = None
    if online:
        try:
            from aipc_chatgpt.setup_judge import plan_setup

            plan = plan_setup(site_id)
            print("── 網上設定計畫（config + LLM/規則）──")
            print(f"  來源：{plan.get('source')}")
            print(f"  {plan.get('message_zh')}")
            print(f"  步驟：{', '.join(plan.get('steps') or [])}")
            print()
        except Exception as exc:
            print(f"（無法載入 site plan：{exc}，改用內建步驟）", file=sys.stderr)
            plan = {"steps": ["install_playwright", "auth_login"]}

    steps = list((plan or {}).get("steps") or [])
    if online and not steps:
        steps = ["install_playwright", "auth_login"]

    online_be = load_online_backend()
    if online and "install_playwright" in steps and not online_be.available():
        print("→ 安裝 Playwright + Chromium（需要網路，約數百 MB）…")
        if non_interactive:
            print(
                "  （non-interactive：請手動 "
                "pip install playwright && python3 -m playwright install chromium）"
            )
        else:
            r1 = _run([sys.executable, "-m", "pip", "install", "--user", "playwright"])
            if r1.returncode != 0:
                print("  pip install playwright 失敗", file=sys.stderr)
                return 1
            r2 = _run([sys.executable, "-m", "playwright", "install", "chromium"])
            if r2.returncode != 0:
                print("  playwright install chromium 失敗", file=sys.stderr)
                return 1
            print("  引擎安裝完成（同一 engine 可供多個網站 pack 使用）。")
            online_be = load_online_backend()

    need_login = online and not skip_login and any(
        s in steps for s in ("auth_login", "auth_login_or_import", "ready")
    )
    # always try login if not ready and online requested
    if online and not skip_login:
        online_be = load_online_backend()
        if not online_be.available():
            print("網上引擎仍不可用，略過登入。", file=sys.stderr)
        elif hasattr(online_be, "auth_login"):
            # skip if already logged in
            already = False
            try:
                already = online_be.auth_status().get("logged_in") is True  # type: ignore[attr-defined]
            except Exception:
                already = False
            if already:
                print("→ 已偵測到登入 session，略過登入窗。")
                mode_slot.set_mode("online")
            else:
                site_label = (plan or {}).get("facts", {}).get("site_title") or "網站"
                print()
                print(f"→ 即將開啟 aipc 專用瀏覽器（站點：{site_label}）。")
                print("  同一 Chromium engine 可掛多個網站 pack；本次只登入此站。")
                print("  請在視窗內完成登入。我們只保存 session／cookie，不記錄密碼。")
                print()
                if not non_interactive:
                    try:
                        input("按 Enter 開啟登入視窗… ")
                    except EOFError:
                        pass
                try:
                    result = online_be.auth_login(timeout_s=300)  # type: ignore[attr-defined]
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                    if result.get("logged_in"):
                        _notify(f"{site_label} 登入成功")
                        mode_slot.set_mode("online")
                        print("→ 已將 mode 設為 online")
                    else:
                        print("→ 尚未偵測到登入；可稍後：aipc-chatgpt auth login")
                except Exception as exc:
                    print(f"登入流程失敗：{exc}", file=sys.stderr)
                    print("稍後可手動：aipc-chatgpt auth login")

    local_ok, _ = _chat_local_ok()
    if local_ok and not online:
        print()
        print("→ 本機快速測試：")
        print('  aipc-assistant --text "用一句話打招呼"')
        mode_slot.set_mode("local")

    report = diagnose()
    print()
    print(format_report(report))
    mark_onboarding_done()
    print()
    print("已記錄首次引導完成（刪 ~/.local/state/aipc-assistant/onboarding_done 可重跑）。")
    print("多網站：aipc-chatgpt sites list  |  aipc-chatgpt sites plan")

    if online:
        return 0 if report.ready_online or report.ready_local else 1
    return 0 if report.ready_local else 1


def friendly_online_error(online_status: dict[str, Any] | None = None) -> str:
    """Human message when online turn fails for setup reasons."""
    lines = [
        "網上助理還沒就緒。第一次使用請跑：",
        "",
        "  aipc-assistant setup --online",
        "",
        "會幫你：檢查環境 → 必要時裝 Chromium → 開窗登入 ChatGPT → 存 session。",
        "完成後：",
        "  aipc-assistant mode online",
        '  aipc-assistant --text "你好"',
    ]
    if online_status:
        lines.append("")
        lines.append(f"（診斷：{json.dumps(online_status, ensure_ascii=False)}）")
    return "\n".join(lines)
