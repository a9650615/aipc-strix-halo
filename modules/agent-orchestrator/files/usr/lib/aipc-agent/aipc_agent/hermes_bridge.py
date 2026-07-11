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
        "Discover facts yourself with tools and search engines — "
        "do not invent titles, cast, or URLs. "
        "Do the task with tools if needed, then stop. "
        "FINAL OUTPUT RULES (critical): "
        "Primary spoken answer: 2 to 5 short sentences in the user's language. "
        "NO tool logs, NO chain-of-thought, NO markdown tables, NO 'Response truncated'. "
        "MULTI-MEDIA: when tools return or open images, maps, charts, video, PDF, or "
        "media-heavy product pages, after the short status list 2+ items (if available), "
        "each line: short label + full https://… so the HUD can show a composite set. "
        "Any topic — not limited to weather. Only URLs from tool output. "
        "For external lookups (codes, titles, live links, product ids, …): "
        "(1) Prefer local skills first when injected — those hosts already worked "
        "on this machine (skill-tree side paths she learned herself). "
        "(2) Use web_search and/or browser search engines "
        "(DuckDuckGo / Bing / Brave / Google / local SearXNG). "
        "(3) Side paths are allowed: follow any useful result site, not only "
        "official storefronts; open 1–2 pages and extract fields from the page. "
        "(4) Only state facts that appear in tool output or provided search hits. "
        "Never invent titles, people, or URLs from memory. "
        "Never answer with only a bare store homepage. "
        "If one path is blocked, try another engine or result site. "
        "If all tools fail, say you could not verify — one short sentence — do not guess. "
        "Successful tool paths are learned into the local skill tree for next time.",
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
                + "\nFollow these local procedures with tools; side-path sites "
                "and search engines are OK. Do not invent answers.\n",
            )
    except Exception:
        pass
    if browser:
        try:
            from aipc_agent.browser_sandbox import prompt_hint

            parts.insert(1, prompt_hint() + "\n")
        except Exception:
            parts.insert(
                1,
                "Browser + search available: web_search, or navigate to "
                "duckduckgo/bing/brave with the query; open any useful result URL.\n",
            )
    # Multi-engine cold-start (default auto ON). Side paths welcome.
    try:
        from aipc_agent import web_hint

        if browser and web_hint.hermes_hint_enabled(has_skill=has_skill, text=text):
            hints = web_hint.hints_for(text, limit=6)
            if hints:
                parts.insert(1, hints + "\n")
                print(
                    f"aipc-agent hermes: web_hint multi-engine chars={len(hints)}",
                    flush=True,
                )
            else:
                # Even with empty hits, give explicit engine URLs to open
                import urllib.parse as _up

                q = _up.quote_plus(text.strip()[:120])
                parts.insert(
                    1,
                    "Search engines (open with browser if web_search empty):\n"
                    f"- https://duckduckgo.com/?q={q}\n"
                    f"- https://search.brave.com/search?q={q}\n"
                    f"- https://www.bing.com/search?q={q}\n"
                    "Open any useful item page from results. "
                    "Prefer local skills for site-specific paths already learned "
                    "on this machine — do not invent titles/cast.\n",
                )
                print("aipc-agent hermes: web_hint empty — injected generic engine URLs", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent hermes: web_hint skip: {exc}", flush=True)
    # Always teach multi-media listing when tools find images/maps/video/PDF
    try:
        from aipc_agent.media_present import presentation_procedure

        tip = presentation_procedure()
        if tip:
            parts.insert(1, tip)
            print("aipc-agent hermes: multi-media presentation injected", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent hermes: media_present skip: {exc}", flush=True)
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


# Capture procedure footprints for async skill learning (not spoken to user).
_URL_RE = re.compile(r"https?://[^\s\]\)\"'`<>，。、]+", re.I)
_TRAIL_HINT = re.compile(
    r"(web_search|browser_|navigate|snapshot|tool[_ ]?call|calling\s+\w+"
    r"|search(ing)?|fetch|open(ed)?\s+http|goto|click|type\s|playwright"
    r"|agent-browser|ddg|duckduckgo|google\.|bing\.|curl\s|wget\s)",
    re.I,
)


def _extract_trail(
    stdout: str = "",
    stderr: str = "",
    *,
    max_chars: int = 1600,
    max_urls: int = 12,
    max_lines: int = 24,
) -> str:
    """Compact tool/URL footprint from Hermes logs for skill_learn (async).

    Learning mentor needs *how* the answer was found, not only the spoken
    reply. No topic keyword gates — only tool/URL shaped lines.
    """
    blob = f"{stdout or ''}\n{stderr or ''}"
    if not blob.strip():
        return ""
    urls: list[str] = []
    seen_u: set[str] = set()
    def _clean_url(u: str) -> str:
        return (u or "").rstrip(".,;:)\\\"'")

    for m in _URL_RE.finditer(blob):
        u = _clean_url(m.group(0))
        if u in seen_u or not u.startswith("http"):
            continue
        seen_u.add(u)
        urls.append(u)
        if len(urls) >= max_urls:
            break
    lines_out: list[str] = []
    seen_l: set[str] = set()
    for raw in blob.splitlines():
        line = raw.strip()
        if len(line) < 6 or len(line) > 220:
            continue
        low = line.lower()
        if low.startswith("session id") or low.startswith("session:"):
            continue
        if line.startswith("──") or line.startswith("---"):
            continue
        if not (_TRAIL_HINT.search(line) or _URL_RE.search(line)):
            continue
        key = re.sub(r"\s+", " ", line)[:160]
        if key in seen_l:
            continue
        seen_l.add(key)
        lines_out.append(key)
        if len(lines_out) >= max_lines:
            break
    parts: list[str] = []
    if urls:
        parts.append("URLS:\n" + "\n".join(f"- {u}" for u in urls))
    if lines_out:
        parts.append("TOOL_LOG:\n" + "\n".join(f"- {ln}" for ln in lines_out))
    out = "\n".join(parts).strip()
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out


def _merge_trails(*chunks: str, max_chars: int = 2000) -> str:
    """Merge trail blobs (stdout + session DB + agent.log)."""
    urls: list[str] = []
    tools: list[str] = []
    seen_u: set[str] = set()
    seen_t: set[str] = set()
    for ch in chunks:
        if not (ch or "").strip():
            continue
        for m in _URL_RE.finditer(ch):
            u = m.group(0).rstrip(".,;:)\\\"'")
            if u not in seen_u and u.startswith("http"):
                seen_u.add(u)
                urls.append(u)
        for raw in ch.splitlines():
            line = raw.strip().lstrip("- ")
            if not line or line.upper().startswith("URLS") or line.upper().startswith(
                "TOOL_LOG"
            ):
                continue
            if _URL_RE.search(line) and line.startswith("http"):
                continue
            if _TRAIL_HINT.search(line) or line.startswith("tool "):
                key = re.sub(r"\s+", " ", line)[:160]
                if key not in seen_t:
                    seen_t.add(key)
                    tools.append(key)
    parts: list[str] = []
    if urls:
        parts.append("URLS:\n" + "\n".join(f"- {u}" for u in urls[:16]))
    if tools:
        parts.append("TOOL_LOG:\n" + "\n".join(f"- {t}" for t in tools[:32]))
    out = "\n".join(parts).strip()
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out


def _trail_from_session_db(home: str, session_id: str) -> str:
    """Read tool calls/results from Hermes state.db before session delete.

    Quiet mode (-Q) suppresses tool previews on stdout; the durable trail for
    grounding/learn lives in ~/.hermes/state.db messages.
    """
    if not session_id:
        return ""
    db = Path(home) / ".hermes" / "state.db"
    if not db.is_file():
        return ""
    try:
        import sqlite3

        uri = f"file:{db}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=3.0)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent hermes: state.db open fail: {exc}", flush=True)
        return ""
    try:
        rows = conn.execute(
            "SELECT role, tool_name, tool_calls, content FROM messages "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent hermes: state.db query fail: {exc}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return ""
    try:
        conn.close()
    except Exception:
        pass
    blobs: list[str] = []
    for role, tool_name, tool_calls, content in rows:
        if tool_name:
            blobs.append(f"tool {tool_name}")
        for field in (tool_calls, content):
            if field:
                blobs.append(str(field)[:2000])
    return _extract_trail("\n".join(blobs), "")


def _trail_from_agent_log(home: str, session_id: str, *, max_lines: int = 40) -> str:
    """Fallback: tool lines from ~/.hermes/logs/agent.log for this session id."""
    if not session_id:
        return ""
    log = Path(home) / ".hermes" / "logs" / "agent.log"
    if not log.is_file():
        return ""
    needle = f"[{session_id}]"
    lines: list[str] = []
    try:
        # Read tail only (log can be large)
        with log.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 400_000))
            chunk = f.read().decode("utf-8", "replace")
    except OSError as exc:
        print(f"aipc-agent hermes: agent.log read fail: {exc}", flush=True)
        return ""
    for raw in chunk.splitlines():
        if needle not in raw:
            continue
        # strip timestamp prefix for trail matcher
        if "] " in raw:
            body = raw.split("] ", 1)[-1]
        else:
            body = raw
        if _TRAIL_HINT.search(body) or "tool " in body.lower() or _URL_RE.search(body):
            lines.append(body.strip()[:200])
            if len(lines) >= max_lines:
                break
    return _extract_trail("\n".join(lines), "")


def _collect_trail(
    home: str,
    *,
    stdout: str,
    stderr: str,
    session_id: str | None,
) -> str:
    """Prefer stdout; always merge session DB + agent.log when quiet hides tools."""
    parts = [
        _extract_trail(stdout or "", stderr or ""),
    ]
    if session_id:
        parts.append(_trail_from_session_db(home, session_id))
        parts.append(_trail_from_agent_log(home, session_id))
    trail = _merge_trails(*parts)
    return trail


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

    # Stable phase labels — do not rotate every few seconds (causes HUD flash).
    _phase = {"msg": "Hermes 工具執行中…"}

    def _push_progress(msg: str, *, thinking: str = "", force: bool = False) -> None:
        msg = (msg or "").strip()[:100]
        if not msg:
            return
        _phase["msg"] = msg
        if _task_jobs is not None and _task_jobs.current_job_id():
            try:
                _task_jobs.job_update(msg, thinking=thinking or msg)
                return
            except Exception:
                pass
        if ux_bridge is not None:
            try:
                elapsed_i = time.monotonic() - t0
                # Fixed prefix + slow-updating elapsed; throttle lives in ux_bridge
                ux_bridge.progress(
                    f"{msg} · {elapsed_i:.0f}s",
                    source="hermes",
                    force=force,
                )
            except Exception:
                pass

    stop_tick = threading.Event()
    out_lines: list[str] = []
    err_lines: list[str] = []
    _push_progress("Hermes 工具執行中…", thinking="准备工具与上下文", force=True)

    def _ticker() -> None:
        # Slow heartbeat only (elapsed). Real phase changes come from tool lines.
        while not stop_tick.wait(8.0):
            _push_progress(_phase["msg"], thinking=_phase["msg"])

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
                        # Human-readable short phase, not raw log spam
                        low2 = line.lower()
                        if "browser" in low2 or "navigate" in low2:
                            snippet = "瀏覽網頁中…"
                        elif "search" in low2:
                            snippet = "搜尋中…"
                        elif "tool" in low2 and "complet" in low2:
                            snippet = "工具完成，整理中…"
                        elif "error" in low2:
                            snippet = "工具出錯，重試中…"
                        else:
                            snippet = "工具執行中…"
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
    # Collect trail BEFORE ephemeral session delete (quiet mode has no tool stdout)
    trail = _collect_trail(
        home,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        session_id=sid,
    )
    if trail:
        print(
            f"aipc-agent hermes: trail_chars={len(trail)} "
            f"urls={trail.count('http')} sid={sid!r}",
            flush=True,
        )
    else:
        print(
            f"aipc-agent hermes: trail empty sid={sid!r} "
            f"(quiet stdout has no tools; state.db/agent.log also empty)",
            flush=True,
        )
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
            try:
                from aipc_agent.grounding import is_ungrounded_lookup

                if is_ungrounded_lookup(text, answer, trail=trail):
                    return {
                        "status": "error",
                        "text": "这次没从网页查到可核实的片名或链接，请稍后再试。",
                        "detail": f"ungrounded_rc={proc.returncode}",
                        "trail": trail,
                    }
            except Exception:
                pass
            return {
                "status": "ok",
                "text": answer,
                "detail": f"rc={proc.returncode}",
                "ephemeral": HERMES_EPHEMERAL,
                "trail": trail,
            }
        return {
            "status": "error",
            "text": "Hermes 执行失败，请改用文字终端重试。",
            "detail": err[:300],
            "trail": trail,
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
            "trail": trail,
        }
    # Block invents: product-code questions need trail or item URL evidence
    try:
        from aipc_agent.grounding import is_ungrounded_lookup

        if is_ungrounded_lookup(text, answer, trail=trail):
            print(
                f"aipc-agent hermes: ungrounded lookup trail={len(trail)} "
                f"preview={answer[:80]!r}",
                flush=True,
            )
            return {
                "status": "error",
                "text": "这次没从网页查到可核实的片名或链接，请稍后再试。",
                "detail": "ungrounded_lookup",
                "ephemeral": HERMES_EPHEMERAL,
                "session_id": sid or "",
                "trail": trail,
            }
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent hermes: grounding skip: {exc}", flush=True)
    print(
        f"aipc-agent hermes: ok {elapsed:.1f}s ephemeral={HERMES_EPHEMERAL} "
        f"sid={sid!r} chars={len(answer)} trail={len(trail)}",
        flush=True,
    )
    return {
        "status": "ok",
        "text": answer,
        "detail": f"{elapsed:.1f}s",
        "ephemeral": HERMES_EPHEMERAL,
        "session_id": sid or "",
        "trail": trail,
    }


def self_test() -> None:
    assert _extract_answer("hello\n\nSession ID: abc123xyz") == "hello"
    assert _extract_session_id("Session ID: abc123xyz") == "abc123xyz"
    sample = (
        "Calling web_search with query ABC-99\n"
        "browser_navigate https://example.com/item/ABC-99\n"
        "Session ID: abc123xyz\n"
        "Title found; cast listed.\n"
    )
    tr = _extract_trail(sample)
    assert "example.com" in tr
    assert "web_search" in tr.lower() or "browser_navigate" in tr
    merged = _merge_trails(
        "URLS:\n- https://a.example/x\n",
        "TOOL_LOG:\n- tool browser_navigate\n",
        "browser_navigate https://b.example/y\n",
    )
    assert "a.example" in merged and "b.example" in merged
    assert _trail_from_session_db("/nonexistent", "nope") == ""
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
