"""Streaming voice turn helpers: sentence split, SSE client, TTS chunk queue.

Used by aipc-voice-stream (openspec: voice-streaming-turn). Stdlib-first.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

# SSE schema (mirrors agent-orchestrator stream_chat; task 1.1 freeze).
SSE_EVENTS = ("session_id", "token", "done", "error")

MIN_CHUNK_CHARS = int(os.environ.get("AIPC_STREAM_TTS_MIN_CHARS", "12"))
MAX_CHUNK_CHARS = int(os.environ.get("AIPC_STREAM_TTS_MAX_CHARS", "64"))
# Prefer strong sentence ends; allow weak pause after min length.
_STRONG_END = re.compile(r"([。！？.!?])")
_WEAK_END = re.compile(r"([，,；;、\n])")


def parse_sse_line(line: str) -> dict[str, Any] | None:
    s = (line or "").strip()
    if not s.startswith("data:"):
        return None
    payload = s[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def feed_sentence_chunks(
    buffer: str,
    *,
    min_chars: int = MIN_CHUNK_CHARS,
    max_chars: int = MAX_CHUNK_CHARS,
    flush: bool = False,
) -> tuple[list[str], str]:
    """Split buffer into speakable chunks; return (ready_chunks, remainder).

    Rules:
    - Prefer cut at 。！？.!? after min_chars
    - Else cut at ，,；;、 after min_chars
    - Else hard cut at max_chars
    - flush=True emits remainder if non-empty (end of stream)
    """
    ready: list[str] = []
    buf = buffer or ""
    while buf:
        if len(buf) < min_chars and not flush:
            break
        # Strong boundary in window
        window = buf[: max(max_chars, min_chars)]
        cut = -1
        for m in _STRONG_END.finditer(window):
            if m.end() >= min_chars:
                cut = m.end()
        if cut < 0:
            for m in _WEAK_END.finditer(window):
                if m.end() >= min_chars:
                    cut = m.end()
        if cut < 0:
            if len(buf) >= max_chars:
                cut = max_chars
            elif flush and buf.strip():
                cut = len(buf)
            else:
                break
        piece = buf[:cut].strip()
        buf = buf[cut:].lstrip()
        if piece:
            ready.append(piece)
        if not flush and len(buf) < min_chars:
            break
    if flush and buf.strip():
        ready.append(buf.strip())
        buf = ""
    return ready, buf


def iter_chat_stream_events(
    text: str,
    *,
    session_id: str,
    url: str | None = None,
    opener=urllib.request.urlopen,
    timeout: float | None = None,
) -> Iterator[dict[str, Any]]:
    """POST /chat/stream and yield parsed event dicts."""
    stream_url = url or os.environ.get(
        "AIPC_VOICE_CHAT_STREAM_URL", "http://127.0.0.1:4100/chat/stream"
    )
    body = json.dumps(
        {"text": text, "session_id": session_id}, ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        stream_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    to = timeout if timeout is not None else float(
        os.environ.get("AIPC_VOICE_STREAM_TIMEOUT", "180")
    )
    with opener(req, timeout=to) as resp:
        while True:
            raw = resp.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace")
            ev = parse_sse_line(line)
            if ev:
                yield ev


class TtsChunkQueue:
    """Ordered TTS playback of text chunks; cancel stops current + drains queue.

    Never mutates master sink volume — delegates to aipc_voice_tts.speak.
    """

    _SENTINEL = object()

    def __init__(
        self,
        speak: Callable[[str], bool] | None = None,
        *,
        on_chunk: Callable[[str], None] | None = None,
    ) -> None:
        self._q: queue.Queue[Any] = queue.Queue()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._speak = speak
        self._on_chunk = on_chunk
        self._errors = 0
        self._played = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run, name="aipc-tts-chunk-q", daemon=True
        )
        self._thread.start()

    def enqueue(self, text: str) -> None:
        if self._cancel.is_set():
            return
        t = (text or "").strip()
        if t:
            self._q.put(t)

    def close(self) -> None:
        self._q.put(self._SENTINEL)

    def cancel(self) -> None:
        self._cancel.set()
        # Drain
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self._q.put(self._SENTINEL)

    def join(self, timeout: float | None = None) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout=timeout)
        return not self._thread.is_alive()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def played_count(self) -> int:
        return self._played

    @property
    def error_count(self) -> int:
        return self._errors

    def _run(self) -> None:
        speak = self._speak
        if speak is None:
            try:
                import aipc_voice_tts as tts

                speak = tts.speak
            except Exception:
                speak = lambda _t: False  # noqa: E731

        while not self._cancel.is_set():
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is self._SENTINEL:
                break
            if self._cancel.is_set():
                break
            if self._on_chunk:
                try:
                    self._on_chunk(str(item))
                except Exception:
                    pass
            try:
                ok = bool(speak(str(item)))
            except Exception:
                ok = False
            if ok:
                self._played += 1
            else:
                self._errors += 1
            if self._cancel.is_set():
                break


# --- Batch-style turn ending for the stream path (0014 #4) ---------------
# The stream worker exits right after TTS; the done→followup sequence must
# survive that exit, so the delayed followup write runs in a small detached
# child instead of a daemon thread.

_IDLE_STATES = frozenset({"listening", "muted", "miss", "detecting", "no_speech"})
_FOLLOWUP_DETAIL = "可说「不对」反馈，或直接说下一句"
_FAREWELL_RE = re.compile(
    r"(先休息|先這樣|先这样|先掛|先挂|先下線|先下线|晚安|再見|再见|掰掰|拜拜"
    r"|bye|goodnight|good night|see you|talk to you later)",
    re.IGNORECASE,
)


def _looks_like_farewell(text: str) -> bool:
    """See aipc_agent.ux_bridge._looks_like_farewell — same idea, same list:
    a closing remark gets no followup invite, just a short readable hold."""
    return bool(_FAREWELL_RE.search(text or ""))


def _ux_status_path() -> Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "aipc-voice-state.json"
    return Path(os.environ.get("HOME", "/tmp")) / ".cache/aipc/voice-state.json"


def done_hold_s() -> float:
    """Overlay hold for the final answer (same env knob as ux_bridge)."""
    try:
        hold = float(os.environ.get("AIPC_UX_DONE_HOLD_S", "20"))
    except ValueError:
        hold = 20.0
    return max(12.0, hold)


def farewell_hold_s() -> float:
    try:
        hold = float(os.environ.get("AIPC_UX_FAREWELL_HOLD_S", "8"))
    except ValueError:
        hold = 8.0
    return max(5.0, hold)


def followup_ttl_s() -> float:
    try:
        ttl = float(os.environ.get("AIPC_UX_FOLLOWUP_TTL_S", "15"))
    except ValueError:
        ttl = 15.0
    return max(5.0, ttl)


def write_turn_state(
    state: str,
    detail: str = "",
    *,
    ttl_s: float | None = None,
    path: Path | None = None,
) -> float:
    """Write overlay status payload directly (announce() cannot carry ttl_s)."""
    p = path or _ux_status_path()
    ts = time.time()
    payload: dict[str, Any] = {
        "state": state,
        "detail": detail,
        "partial": detail,
        "label": "",
        "source": "voice-stream",
        "ts": ts,
    }
    if ttl_s is not None and ttl_s > 0:
        payload["ttl_s"] = float(ttl_s)
        payload["hold_s"] = float(ttl_s)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"aipc-voice-stream: ux write fail: {exc}", file=sys.stderr, flush=True)
    return ts


def _followup_should_write(cur: dict, done_ts: float) -> bool:
    """Only follow up on OUR done. Idle/mic-noise states (the wake service
    writes `listening` after the worker exits) do not cancel the follow-up;
    any newer active turn or a different done does."""
    state = str(cur.get("state") or "")
    try:
        ts = float(cur.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    if state == "done":
        return abs(ts - done_ts) <= 0.5
    return state in _IDLE_STATES


def _followup_main(args: list[str]) -> int:
    """Detached child: sleep the done hold, then show the follow-up hint."""
    path, done_ts, hold, ttl = Path(args[0]), float(args[1]), float(args[2]), float(args[3])
    if hold > 0:
        time.sleep(hold)
    try:
        cur = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cur = {}
    if not isinstance(cur, dict) or not _followup_should_write(cur, done_ts):
        return 0
    write_turn_state("followup", _FOLLOWUP_DETAIL, ttl_s=ttl, path=path)
    return 0


def finish_turn_ux(detail: str, *, spawn=None) -> float:
    """End a stream turn batch-style: done (hold) → followup (ttl).

    A farewell-style reply ("好的，那我就先休息了") skips the followup invite
    entirely — nothing to follow up on, and no child gets spawned to write it.

    Returns the done timestamp. spawn is injectable for tests; the default
    detaches a tiny python child so the followup write survives worker exit.
    """
    text = (detail or "完成").strip()
    farewell = _looks_like_farewell(text)
    hold = farewell_hold_s() if farewell else done_hold_s()
    ts = write_turn_state("done", text, ttl_s=hold)
    if farewell:
        return ts
    argv = [
        sys.executable,
        "-c",
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import aipc_voice_stream as m; "
        "raise SystemExit(m._followup_main(sys.argv[2:]))",
        str(Path(__file__).resolve().parent),
        str(_ux_status_path()),
        f"{ts:.6f}",
        f"{hold:.1f}",
        f"{followup_ttl_s():.1f}",
    ]
    try:
        if spawn is not None:
            spawn(argv)
        else:
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    except OSError as exc:
        print(f"aipc-voice-stream: followup spawn fail: {exc}", file=sys.stderr, flush=True)
    return ts


def self_test() -> int:
    assert set(SSE_EVENTS) == {"session_id", "token", "done", "error"}
    assert parse_sse_line('data: {"event":"token","text":"a"}')["text"] == "a"
    assert parse_sse_line("data: [DONE]") is None

    chunks, rest = feed_sentence_chunks("你好。", min_chars=2, max_chars=64)
    assert chunks == ["你好。"] and rest == ""

    chunks, rest = feed_sentence_chunks(
        "这是一句比较长的中文没有标点" * 2, min_chars=12, max_chars=20
    )
    assert chunks and all(len(c) <= 20 for c in chunks)

    chunks, rest = feed_sentence_chunks("短", min_chars=12, max_chars=64, flush=False)
    assert chunks == [] and rest == "短"
    chunks, rest = feed_sentence_chunks("短", min_chars=12, max_chars=64, flush=True)
    assert chunks == ["短"] and rest == ""

    # Queue order + cancel
    played: list[str] = []

    def _speak(t: str) -> bool:
        if t == "B":
            time.sleep(0.05)
        played.append(t)
        return True

    q = TtsChunkQueue(speak=_speak)
    q.start()
    q.enqueue("A")
    q.enqueue("B")
    q.close()
    assert q.join(timeout=2.0)
    assert played == ["A", "B"]

    played.clear()
    q2 = TtsChunkQueue(speak=lambda t: played.append(t) or True)
    q2.start()
    q2.enqueue("X")
    q2.cancel()
    q2.join(timeout=1.0)
    assert q2.cancelled

    print("aipc_voice_stream: self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
