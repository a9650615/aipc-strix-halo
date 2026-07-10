"""Read-only desktop describe: screenshot → LiteLLM VLM (vlm-screen).

Product path for “看一下桌面 / what's on my screen” — no mouse/keyboard
injection and no agent-gate grant required (view-only). Input control stays
behind agent-screen-control + gate.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

LITELLM_BASE_URL = os.environ.get("AIPC_LITELLM_URL", "http://127.0.0.1:4000").rstrip("/")
# Prefer small/fast screen VLM; set AIPC_SCREEN_VLM=vlm-qwen2vl for uncensored vision.
VLM_MODEL = os.environ.get("AIPC_SCREEN_VLM", "vlm-screen")
TIMEOUT = float(os.environ.get("AIPC_SCREEN_VLM_TIMEOUT", "180"))
# Cap long edge so VLM loads/infers faster on APU (full 4K PNGs are multi-MB base64).
MAX_EDGE = int(os.environ.get("AIPC_SCREEN_MAX_EDGE", "1280"))

DEFAULT_PROMPT_ZH = (
    "这是用户电脑桌面的截图。请用简洁中文说明："
    "1) 主要窗口/应用；2) 能读到的关键文字；3) 明显按钮或入口。"
    "不要编造看不清的内容；最多 8 行。"
)
DEFAULT_PROMPT_EN = (
    "This is a desktop screenshot. Briefly list: "
    "1) main windows/apps 2) readable text 3) obvious buttons/links. "
    "Do not invent unreadable text. Max 8 lines."
)


def _looks_chinese(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in (text or ""))


def _desktop_user() -> str:
    """Interactive desktop owner — never root (orchestrator is often root)."""
    for key in ("AIPC_PRIMARY_USER", "AIPC_MEMORY_USER_ID", "SUDO_USER"):
        v = (os.environ.get(key) or "").strip()
        if v and v != "root":
            return v
    try:
        import pwd

        return pwd.getpwuid(1000).pw_name
    except Exception:
        return "birdyo"


def _desktop_env() -> dict[str, str]:
    """Env for screenshot tools against the interactive Wayland/X11 session."""
    user = _desktop_user()
    try:
        import pwd

        uid = pwd.getpwnam(user).pw_uid
        home = pwd.getpwnam(user).pw_dir
    except Exception:
        uid = 1000
        home = f"/home/{user}"
    xdg = f"/run/user/{uid}"
    env = os.environ.copy()
    env["HOME"] = home
    env["USER"] = user
    env["LOGNAME"] = user
    env["XDG_RUNTIME_DIR"] = xdg
    env.setdefault("DISPLAY", os.environ.get("DISPLAY", ":0"))
    # Prefer real session Wayland if present
    for cand in ("wayland-0", "wayland-1"):
        if Path(xdg, cand).exists() or Path(xdg, cand).is_socket():
            env["WAYLAND_DISPLAY"] = cand
            break
    env.setdefault("WAYLAND_DISPLAY", os.environ.get("WAYLAND_DISPLAY", "wayland-0"))
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={xdg}/bus"
    return env


def capture_screenshot() -> bytes:
    """Capture primary desktop as PNG. Prefer KDE spectacle (Wayland).

    Orchestrator often runs as root/systemd — run capture as the desktop
    user so PipeWire/Wayland session is visible.
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = Path(tmp.name)
    # World-writable so desktop user can write when we runuser
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    user = _desktop_user()
    env = _desktop_env()
    # Write into a path the desktop user owns if possible
    user_tmp = Path(env["XDG_RUNTIME_DIR"]) / "aipc-screen-see.png"
    out_path = user_tmp if Path(env["XDG_RUNTIME_DIR"]).is_dir() else path

    def _wrap(cmd: list[str]) -> list[str]:
        if os.geteuid() == 0 and user and user != "root":
            return ["runuser", "-u", user, "--", "env", *[f"{k}={v}" for k, v in (
                ("HOME", env["HOME"]),
                ("USER", user),
                ("XDG_RUNTIME_DIR", env["XDG_RUNTIME_DIR"]),
                ("DISPLAY", env.get("DISPLAY", ":0")),
                ("WAYLAND_DISPLAY", env.get("WAYLAND_DISPLAY", "wayland-0")),
                ("DBUS_SESSION_BUS_ADDRESS", env["DBUS_SESSION_BUS_ADDRESS"]),
            )], *cmd]
        return cmd

    try:
        cmds: list[list[str]] = []
        if shutil.which("spectacle"):
            cmds.append(["spectacle", "-b", "-n", "-o", str(out_path)])
        if shutil.which("gnome-screenshot"):
            cmds.append(["gnome-screenshot", "-f", str(out_path)])
        if shutil.which("grim"):
            cmds.append(["grim", str(out_path)])
        if shutil.which("import"):
            cmds.append(["import", "-window", "root", str(out_path)])
        last_err = "no screenshot tool (install spectacle)"
        for cmd in cmds:
            try:
                subprocess.run(
                    _wrap(cmd),
                    check=True,
                    capture_output=True,
                    timeout=15,
                    env=env if os.geteuid() != 0 else None,
                )
                data = out_path.read_bytes() if out_path.is_file() else b""
                if len(data) > 64:
                    return data
                last_err = f"empty file from {cmd[0]}"
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                err = ""
                if isinstance(exc, subprocess.CalledProcessError):
                    err = (exc.stderr or b"").decode(errors="replace")[:200]
                last_err = f"{cmd[0]}: {exc} {err}".strip()
                continue
        raise RuntimeError(f"screenshot failed: {last_err}")
    finally:
        path.unlink(missing_ok=True)
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass


def _downscale_png(png: bytes, max_edge: int = MAX_EDGE) -> bytes:
    """Shrink PNG via ImageMagick if available; else return original."""
    if max_edge <= 0 or len(png) < 1024:
        return png
    convert = shutil.which("magick") or shutil.which("convert")
    if not convert:
        return png
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as src:
            src.write(png)
            src_path = Path(src.name)
        dst_path = src_path.with_suffix(".out.png")
        try:
            # geometry: fit inside max_edge×max_edge, only shrink (>)
            cmd = [convert, str(src_path), "-resize", f"{max_edge}x{max_edge}>", str(dst_path)]
            subprocess.run(cmd, check=True, capture_output=True, timeout=20)
            out = dst_path.read_bytes()
            if len(out) > 64:
                return out
        finally:
            src_path.unlink(missing_ok=True)
            dst_path.unlink(missing_ok=True)
    except Exception:
        return png
    return png


def describe_desktop(
    user_text: str = "",
    *,
    model: str | None = None,
    prompt: str | None = None,
) -> dict:
    """Capture desktop and describe via LiteLLM. Returns status dict."""
    model = model or VLM_MODEL
    if prompt is None:
        prompt = DEFAULT_PROMPT_ZH if _looks_chinese(user_text) else DEFAULT_PROMPT_EN
        extra = (user_text or "").strip()
        if extra and len(extra) > 2:
            prompt = f"{prompt}\nUser question: {extra}"

    try:
        png = capture_screenshot()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": f"capture: {exc}", "description": ""}

    png = _downscale_png(png)
    b64 = base64.b64encode(png).decode()
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 384,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{LITELLM_BASE_URL}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            reply = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        return {"status": "error", "detail": f"HTTP {exc.code}: {detail}", "description": ""}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc), "description": ""}

    try:
        msg = reply["choices"][0]["message"]
        text = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        return {"status": "error", "detail": f"bad reply: {exc}", "description": ""}
    if not text:
        return {"status": "error", "detail": "empty VLM content", "description": ""}
    return {
        "status": "ok",
        "model": model,
        "description": text,
        "bytes": len(png),
    }


def wants_screen_see(text: str) -> bool:
    """Keyword match for desktop-see requests."""
    raw = (text or "").strip().lower()
    if not raw:
        return False
    phrases = (
        "看桌面",
        "看螢幕",
        "看屏幕",
        "螢幕上",
        "屏幕上",
        "桌面上",
        "看见什么",
        "看見什麼",
        "看到什么",
        "看到什麼",
        "画面上",
        "畫面上",
        "截图",
        "截圖",
        "what's on screen",
        "whats on screen",
        "what is on screen",
        "what do you see",
        "describe screen",
        "describe the screen",
        "describe desktop",
        "look at screen",
        "look at desktop",
        "see my screen",
        "see the screen",
        "screen look",
    )
    if any(p in raw for p in phrases):
        return True
    # compact: drop spaces and common filler (一下/一下下)
    compact = raw.replace(" ", "").replace("一下下", "").replace("一下", "")
    if any(
        p in compact
        for p in (
            "看桌面",
            "看屏幕",
            "看螢幕",
            "螢幕上有",
            "屏幕上有",
            "桌面有什么",
            "桌面有什麼",
        )
    ):
        return True
    # 看…桌面 / describe … screen with short filler in between
    if any(v in raw for v in ("看", "look", "see", "describe", "screenshot")) and any(
        n in raw for n in ("桌面", "螢幕", "屏幕", "screen", "desktop")
    ):
        return True
    return False


def self_test() -> None:
    assert wants_screen_see("看一下桌面")
    assert wants_screen_see("what's on screen?")
    assert not wants_screen_see("今天天气怎么样")
    assert _looks_chinese("看桌面")
    assert not _looks_chinese("hello")
    print("screen_see self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    r = describe_desktop(" ".join(a for a in sys.argv[1:] if a != "--"))
    print(json.dumps(r, ensure_ascii=False, indent=2))
