"""Invoke local Hermes CLI for complex tool-using tasks.

Hermes (coder-agentic uncensored via LiteLLM + terminal/browser/MCP) is the heavy agent.
Voice /chat defaults to assistant-gemma; keyword/tool route hands
complex work here.

Default is ephemeral: tag session --source aipc-voice, then delete it so
Hermes history is not kept. mem0 is still used read-side (facts injected into
the query) and Hermes may use its own mem0 MCP when enabled in ~/.hermes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from aipc_agent import memory

HERMES_BIN = os.environ.get("AIPC_HERMES_BIN", "hermes")
HERMES_USER = os.environ.get("AIPC_HERMES_USER", "")  # empty → auto primary desktop user
HERMES_HOME = os.environ.get("AIPC_HERMES_HOME", "")
# Long multi-step tool work (research / implement / multi-file). Voice once
# CHAT_TIMEOUT must stay above HERMES_VOICE_TIMEOUT (see aipc-voice-once).
HERMES_TIMEOUT = float(os.environ.get("AIPC_HERMES_TIMEOUT", "900"))
HERMES_VOICE_TIMEOUT = float(os.environ.get("AIPC_HERMES_VOICE_TIMEOUT", "720"))
# Explicit long-task / background jobs (research, full projects).
HERMES_LONG_TIMEOUT = float(os.environ.get("AIPC_HERMES_LONG_TIMEOUT", "1800"))
HERMES_MAX_TURNS = int(os.environ.get("AIPC_HERMES_MAX_TURNS", "48"))
HERMES_VOICE_MAX_TURNS = int(os.environ.get("AIPC_HERMES_VOICE_MAX_TURNS", "32"))
HERMES_LONG_MAX_TURNS = int(os.environ.get("AIPC_HERMES_LONG_MAX_TURNS", "64"))
# 1 = delete Hermes session after run (no history trail). 0 = keep.
HERMES_EPHEMERAL = os.environ.get("AIPC_HERMES_EPHEMERAL", "1") not in (
    "0",
    "false",
    "no",
)
# Inject mem0 recall into the query (read-only). Hermes may also use MCP mem0.
HERMES_USE_MEM0 = os.environ.get("AIPC_HERMES_USE_MEM0", "1") not in (
    "0",
    "false",
    "no",
)
HERMES_SOURCE = os.environ.get("AIPC_HERMES_SOURCE", "aipc-voice")


def _primary_user_home() -> tuple[str, str]:
    """Return (username, home) for the desktop user hermes config lives under."""
    if HERMES_USER and HERMES_HOME:
        return HERMES_USER, HERMES_HOME
    if HERMES_USER:
        try:
            import pwd

            return HERMES_USER, pwd.getpwnam(HERMES_USER).pw_dir
        except (KeyError, ImportError):
            pass
    # Prefer birdyo-style primary from /run/user
    try:
        import pwd

        uids = [int(d) for d in os.listdir("/run/user") if d.isdigit() and int(d) >= 1000]
        if uids:
            pw = pwd.getpwuid(min(uids))
            return pw.pw_name, pw.pw_dir
    except (OSError, KeyError, ValueError):
        pass
    home = os.environ.get("HOME") or str(Path.home())
    user = os.environ.get("USER") or "birdyo"
    return user, home


def _resolve_hermes() -> str | None:
    if Path(HERMES_BIN).is_file():
        return HERMES_BIN
    found = shutil.which(HERMES_BIN)
    if found:
        return found
    user, home = _primary_user_home()
    cand = Path(home) / ".local/bin/hermes"
    if cand.is_file():
        return str(cand)
    return None


def available() -> bool:
    return _resolve_hermes() is not None


def _build_env(home: str, user: str) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = home
    env["USER"] = user
    env["LOGNAME"] = user
    # Desktop session for any GUI/terminal tools Hermes may open
    uid = ""
    try:
        import pwd

        uid = str(pwd.getpwnam(user).pw_uid)
    except (KeyError, ImportError):
        pass
    xdg = f"/run/user/{uid}" if uid else env.get("XDG_RUNTIME_DIR", "")
    if xdg and Path(xdg).is_dir():
        env["XDG_RUNTIME_DIR"] = xdg
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={xdg}/bus")
        env.setdefault("PULSE_SERVER", f"unix:{xdg}/pulse/native")
    path = env.get("PATH", "/usr/bin")
    local_bin = str(Path(home) / ".local/bin")
    if local_bin not in path.split(":"):
        env["PATH"] = f"{local_bin}:{path}"
    return env


def _is_unusable_answer(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 4:
        return True
    low = t.lower()
    bad = (
        "response truncated",
        "output length limit",
        "no reply",
        "empty content",
        "after retries",
        "fallback providers",
        "任务跑完了，但没有可读",
    )
    return any(b in low or b in t for b in bad)


def _build_query(text: str, session_id: str, *, browser: bool = False) -> str:
    parts = [
        "You are helping via the aipc voice assistant. "
        "Discover facts yourself with tools — do not invent titles or URLs. "
        "Do the task with tools if needed, then stop. "
        "FINAL OUTPUT RULES (critical): "
        "print ONLY the spoken answer — 2 to 4 short sentences in the user's language; "
        "NO tool logs, NO thinking, NO markdown tables, NO 'Response truncated' errors. "
        "For lookup requests: ALWAYS include (1) the work title found via tools, "
        "(2) key cast/details when available, (3) at least one concrete URL from tools. "
        "Prefer specific facts over generic 'how to search' advice. "
        "If tools fail, say one short failure sentence.",
        "",
        f"User request:\n{text.strip()}",
    ]
    # Local skills first (paths she already learned on this machine)
    has_skill = False
    try:
        from aipc_agent.skill_learn import skills_for_query

        skill_blob = skills_for_query(text, limit=2)
        if skill_blob:
            has_skill = True
            parts.insert(
                1,
                skill_blob
                + "\nFollow these local procedures to find the answer with tools; "
                "do not rely on prior memorized answers alone.\n",
            )
    except Exception:
        pass
    if browser:
        try:
            from aipc_agent.browser_sandbox import prompt_hint

            parts.insert(
                1,
                prompt_hint()
                + "\nYou MUST use web_search and/or browser_navigate to obtain "
                "title and URL before answering. The sandbox is for discovering "
                "the lookup path, not for guessing.\n",
            )
        except Exception:
            parts.insert(
                1,
                "Browser tools available: you MUST use web_search / browser_navigate "
                "to discover title and URL; do not invent them.\n",
            )
    # Optional web_hint: only when no local skill yet (cold start assist).
    # Disabled by default for Hermes when browser is on — she should learn paths.
    # Set AIPC_WEB_HINT_HERMES=1 to re-enable inject for debugging.
    try:
        from aipc_agent import web_hint

        hermes_hint = os.environ.get("AIPC_WEB_HINT_HERMES", "0") not in (
            "0",
            "false",
            "no",
            "off",
        )
        if hermes_hint and (web_hint.lookup_wants_web(text) or browser) and not has_skill:
            hints = web_hint.hints_for(text, limit=5)
            if hints:
                parts.insert(1, hints + "\n")
                print(
                    f"aipc-agent hermes: web_hint cold-start chars={len(hints)}",
                    flush=True,
                )
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent hermes: web_hint skip: {exc}", flush=True)
    if HERMES_USE_MEM0:
        try:
            facts = memory.recall(
                text, session_id, limit=5, agent=memory.AGENT_HERMES
            )
        except Exception:
            facts = ""
        # Drop failure/poison memories that teach "don't bother searching"
        if facts:
            poison = (
                "blocked",
                "cannot be retrieved",
                "无法",
                "無法",
                "连不上",
                "truncated",
                "Google 搜尋被擋",
            )
            kept = []
            for line in facts.splitlines():
                low = line.lower()
                if any(p.lower() in low or p in line for p in poison):
                    continue
                kept.append(line)
            facts = "\n".join(kept).strip()
        if facts:
            parts.insert(
                1,
                f"Relevant Hermes-agent memories (not daily/chat):\n{facts}\n",
            )
        try:
            from aipc_agent import agent_context

            hist = agent_context.format_history(session_id, memory.AGENT_HERMES)
            if hist:
                parts.insert(1, f"Recent Hermes turns:\n{hist}\n")
        except Exception:
            pass
    return "\n".join(parts)


_SESSION_RE = re.compile(
    r"(?:session[_ ]?id|Session ID|session)\s*[:=]\s*([A-Za-z0-9_-]{6,})",
    re.I,
)


def _extract_session_id(blob: str) -> str | None:
    m = _SESSION_RE.search(blob or "")
    return m.group(1) if m else None


def _extract_answer(stdout: str) -> str:
    """Quiet mode prints final answer; strip banners / progress if any leaked."""
    text = (stdout or "").strip()
    if not text:
        return ""
    # Drop common trailing session footer lines
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        low = line.strip().lower()
        if low.startswith("session id") or low.startswith("session:"):
            continue
        if low.startswith("──") or low.startswith("---"):
            continue
        kept.append(line)
    out = "\n".join(kept).strip()
    # Prefer last non-empty paragraph as final answer
    paras = [p.strip() for p in re.split(r"\n\s*\n", out) if p.strip()]
    if paras:
        return paras[-1][:2000]
    return out[:2000]


def _delete_session(hermes: str, session_id: str, env: dict[str, str], argv_prefix: list[str]) -> None:
    if not session_id:
        return
    try:
        subprocess.run(
            [*argv_prefix, hermes, "sessions", "delete", session_id, "--yes"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # --yes may not exist on older hermes; try without
        try:
            subprocess.run(
                [*argv_prefix, hermes, "sessions", "delete", session_id],
                env=env,
                input="y\n",
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _is_voice_session(session_id: str) -> bool:
    s = (session_id or "").lower()
    return any(k in s for k in ("voice", "wake", "ptt", "aipc-voice"))


def run(
    text: str,
    session_id: str = "voice",
    *,
    long_task: bool = False,
    wall: float | None = None,
    max_turns: int | None = None,
) -> dict:
    """Run Hermes once. Returns {status, text, detail?, ephemeral?}."""
    hermes = _resolve_hermes()
    if not hermes:
        return {
            "status": "unavailable",
            "text": "本机 Hermes 未安装或找不到命令。",
            "detail": "hermes binary missing",
        }

    user, home = _primary_user_home()
    env = _build_env(home, user)
    # Sandbox browser when task shape needs live crawl (skill learning / research)
    use_browser = False
    try:
        from aipc_agent import browser_sandbox

        use_browser = browser_sandbox.needs_browser(text, long_task=long_task)
        if use_browser:
            env = browser_sandbox.hermes_env(env)
            browser_sandbox.ensure_profile()
            print(
                f"aipc-agent hermes: browser-sandbox on path={browser_sandbox.SANDBOX_ROOT}",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent hermes: browser-sandbox skip: {exc}", flush=True)
        use_browser = False
    query = _build_query(text, session_id, browser=use_browser)
    voice = _is_voice_session(session_id)
    if wall is None:
        if long_task:
            wall = HERMES_LONG_TIMEOUT
        elif voice:
            wall = HERMES_VOICE_TIMEOUT
        else:
            wall = HERMES_TIMEOUT
    if max_turns is None:
        if long_task:
            max_turns = HERMES_LONG_MAX_TURNS
        elif voice:
            # Short voice lookups thrash if turns are huge; keep tools bounded.
            max_turns = min(HERMES_VOICE_MAX_TURNS, int(os.environ.get("AIPC_HERMES_VOICE_MAX_TURNS", "16")))
        else:
            max_turns = HERMES_MAX_TURNS

    argv_prefix: list[str] = []
    if os.geteuid() == 0 and user and user != "root":
        # Orchestrator often runs as root; Hermes config is per-user.
        argv_prefix = ["runuser", "-u", user, "--"]

    cmd = [
        *argv_prefix,
        hermes,
        "chat",
        "-q",
        query,
        "-Q",
        "--source",
        HERMES_SOURCE,
        "--max-turns",
        str(max(1, max_turns)),
        "--accept-hooks",
    ]
    if use_browser:
        # Equip browser toolset (navigate/snapshot + web_search) for this run
        cmd.extend(["-t", "browser"])

    t0 = time.monotonic()
    # Live UX ticker so voice users are not stuck on a silent "thinking" screen.
    try:
        from aipc_agent import ux_bridge

        ux_bridge.progress("Hermes 啟動中…", source="hermes")
    except Exception:
        ux_bridge = None  # type: ignore

    try:
        from aipc_agent import task_jobs as _task_jobs
    except Exception:
        _task_jobs = None  # type: ignore

    def _push_progress(msg: str, *, thinking: str = "") -> None:
        msg = (msg or "").strip()[:120]
        if not msg:
            return
        if _task_jobs is not None and _task_jobs.current_job_id():
            try:
                _task_jobs.job_update(msg, thinking=thinking or msg)
                return
            except Exception:
                pass
        if ux_bridge is not None:
            try:
                elapsed_i = time.monotonic() - t0
                ux_bridge.progress(f"{msg}（{elapsed_i:.0f}s）", source="hermes")
            except Exception:
                pass

    stop_tick = threading.Event()
    out_lines: list[str] = []
    err_lines: list[str] = []
    _push_progress("Hermes 啟動中…", thinking="准备工具与上下文")

    def _ticker() -> None:
        phases = (
            "Hermes 思考中…",
            "工具執行中…",
            "還在處理，請稍候…",
            "整理結果中…",
        )
        n = 0
        while not stop_tick.wait(2.5):
            n += 1
            msg = phases[min(n, len(phases) - 1)]
            # Prefer last interesting log line if we saw one
            if out_lines:
                tail = out_lines[-1].strip()
                if 4 < len(tail) < 80 and not tail.lower().startswith("session"):
                    msg = tail[:80]
            _push_progress(msg, thinking=msg)

    tick_thread = threading.Thread(target=_ticker, name="hermes-ux", daemon=True)
    tick_thread.start()

    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=home,
        )
        assert proc.stdout is not None and proc.stderr is not None

        def _read(stream, bucket: list[str]) -> None:
            try:
                for line in stream:
                    bucket.append(line.rstrip("\n"))
                    low = line.lower()
                    interesting = any(
                        k in low
                        for k in (
                            "tool",
                            "running",
                            "calling",
                            "execut",
                            "search",
                            "read",
                            "write",
                            "bash",
                            "shell",
                            "think",
                            "plan",
                            "step",
                            "file",
                            "npm",
                            "git",
                            "error",
                        )
                    )
                    if interesting:
                        snippet = line.strip()[:80]
                        if snippet:
                            _push_progress(snippet, thinking=snippet)
            except Exception:
                pass

        t_out = threading.Thread(target=_read, args=(proc.stdout, out_lines), daemon=True)
        t_err = threading.Thread(target=_read, args=(proc.stderr, err_lines), daemon=True)
        t_out.start()
        t_err.start()
        try:
            rc = proc.wait(timeout=wall)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            stop_tick.set()
            if ux_bridge is not None:
                try:
                    ux_bridge.progress("Hermes 超時", state="error", source="hermes")
                except Exception:
                    pass
            return {
                "status": "timeout",
                "text": f"Hermes 处理超时（{wall:.0f}s），请简化任务或稍后再试。",
                "detail": "timeout",
            }
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        # shim for returncode/stdout access below
        class _R:
            returncode = rc
            stdout = "\n".join(out_lines)
            stderr = "\n".join(err_lines)

        proc = _R()  # type: ignore
    except OSError as exc:
        stop_tick.set()
        return {
            "status": "error",
            "text": "无法启动 Hermes。",
            "detail": str(exc),
        }
    finally:
        stop_tick.set()

    elapsed = time.monotonic() - t0
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    sid = _extract_session_id(combined)
    if HERMES_EPHEMERAL and sid:
        _delete_session(hermes, sid, env, argv_prefix)

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "hermes failed").strip()
        print(
            f"aipc-agent hermes: rc={proc.returncode} {elapsed:.1f}s err={err[:200]}",
            flush=True,
        )
        # Sometimes quiet mode still prints answer on partial failure
        answer = _extract_answer(proc.stdout or "")
        if answer and len(answer) > 8:
            return {
                "status": "ok",
                "text": answer,
                "detail": f"rc={proc.returncode}",
                "ephemeral": HERMES_EPHEMERAL,
            }
        return {
            "status": "error",
            "text": "Hermes 执行失败，请改用文字终端重试。",
            "detail": err[:300],
        }

    answer = _extract_answer(proc.stdout or "")
    if not answer:
        answer = "任务跑完了，但没有可读的文字回复。"
    if _is_unusable_answer(answer):
        print(
            f"aipc-agent hermes: unusable {elapsed:.1f}s sid={sid!r} "
            f"preview={answer[:80]!r}",
            flush=True,
        )
        return {
            "status": "error",
            "text": "这次没查到可用结果，请换个说法或稍后再试。",
            "detail": f"unusable_answer:{answer[:120]}",
            "ephemeral": HERMES_EPHEMERAL,
            "session_id": sid or "",
        }
    print(
        f"aipc-agent hermes: ok {elapsed:.1f}s ephemeral={HERMES_EPHEMERAL} "
        f"sid={sid!r} chars={len(answer)}",
        flush=True,
    )
    return {
        "status": "ok",
        "text": answer,
        "detail": f"{elapsed:.1f}s",
        "ephemeral": HERMES_EPHEMERAL,
        "session_id": sid or "",
    }


def self_test() -> None:
    assert _extract_answer("hello\n\nSession ID: abc123xyz") == "hello"
    assert _extract_session_id("Session ID: abc123xyz") == "abc123xyz"
    assert HERMES_VOICE_TIMEOUT < float(os.environ.get("AIPC_VOICE_CHAT_TIMEOUT", "780"))
    assert HERMES_LONG_TIMEOUT >= HERMES_VOICE_TIMEOUT
    print("hermes_bridge self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    if len(sys.argv) > 1:
        r = run(" ".join(sys.argv[1:]), "cli-test")
        print(r)
        sys.exit(0 if r.get("status") == "ok" else 1)
