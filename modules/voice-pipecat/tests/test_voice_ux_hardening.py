"""0014-voice-ux-hardening Phase A self-checks (static tier, headless).

Overlay lifecycle (active-state watchdog, follow-up hold guard, single
instance, session-restore opt-out) + stream turn ending (done→followup)
+ no per-token overlay ticker. Qt parts run offscreen and skip cleanly
when PySide6 is missing (same pattern as tools/tests/test_overlay_dock.py).
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import threading
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]
VOICE_LIB = MODULE / "files" / "usr" / "lib" / "aipc-voice"
OVL = VOICE_LIB / "aipc_voice_overlay.py"
STREAM_BIN = MODULE / "files" / "usr" / "bin" / "aipc-voice-stream"

sys.path.insert(0, str(VOICE_LIB))


def _load_source(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _overlay_mod():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return _load_source("aipc_voice_overlay", OVL)


@pytest.fixture(autouse=True)
def _isolated_overlay_socket(tmp_path, monkeypatch):
    """OverlayPanel() binds overlay_sock_path() (from $XDG_RUNTIME_DIR) as its
    control socket. Without this, every test in this file that constructs a
    panel unlinks-and-rebinds the REAL production socket on any machine
    where the live aipc-voice-overlay service happens to be running —
    kicking the real overlay off its own socket. Isolate it per test."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))


def _panel(m):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    return m.OverlayPanel()


# --- #2 active-state watchdog ------------------------------------------------


def test_watchdog_active_states_get_deadline():
    m = _overlay_mod()
    p = _panel(m)
    for state in ("speaking", "thinking", "working", "bg_task"):
        t0 = time.time()
        p.apply_status({"state": state, "detail": "進行中", "ts": t0})
        assert p._hide_at is not None, state
        assert 100.0 <= p._hide_at - t0 <= 140.0, state  # default 120s


def test_watchdog_deadline_anchors_to_stale_ts_not_now():
    m = _overlay_mod()
    p = _panel(m)
    # A restarted overlay reading a status.json from a turn that died 16
    # minutes ago (no terminal done/error ever written) must not treat it
    # as fresh — that replays a full new AIPC_OVERLAY_ACTIVE_TIMEOUT_S of
    # phantom "answering" spinner on every restart.
    stale_ts = time.time() - 16 * 60
    p.apply_status({"state": "speaking", "detail": "你好。世界。", "ts": stale_ts})
    assert p._hide_at is not None
    assert p._hide_at < time.time()  # already expired, not a fresh 120s grace


def test_watchdog_env_override(monkeypatch):
    m = _overlay_mod()
    monkeypatch.setenv("AIPC_OVERLAY_ACTIVE_TIMEOUT_S", "7")
    p = _panel(m)
    t0 = time.time()
    p.apply_status({"state": "speaking", "detail": "x", "ts": t0})
    assert p._hide_at is not None and 6.0 <= p._hide_at - t0 <= 8.5


# --- #3 follow-up hold guard --------------------------------------------------


def test_hold_guard_ignores_listening_during_done_window():
    m = _overlay_mod()
    p = _panel(m)
    p.apply_status(
        {"state": "done", "detail": "這是答案" * 5, "ts": time.time(), "ttl_s": 20}
    )
    assert p._hold_until > time.time()
    hide_at = p._hide_at
    p.apply_status({"state": "listening", "ts": time.time()})
    assert p._state == "done"  # write ignored — answer keeps its hold
    assert p._hide_at == hide_at
    # Window closed → listening applies again (0.15s quick hide path)
    p._hold_until = 0.0
    p.apply_status({"state": "listening", "ts": time.time()})
    assert p._state == "listening"
    assert p._hide_at is not None and p._hide_at - time.time() < 2.0


def test_followup_has_ttl_and_extended_hold():
    m = _overlay_mod()
    p = _panel(m)
    t0 = time.time()
    p.apply_status({"state": "followup", "detail": "可接話", "ts": t0, "ttl_s": 30})
    assert p._hide_at is not None and 25.0 <= p._hide_at - t0 <= 35.0
    assert p._hold_until >= p._hide_at


def test_new_active_turn_closes_hold_window():
    m = _overlay_mod()
    p = _panel(m)
    p.apply_status({"state": "done", "detail": "答案答案答案答案", "ts": time.time()})
    assert p._hold_until > time.time()
    p.apply_status({"state": "wake", "detail": "", "ts": time.time()})
    assert p._hold_until == 0.0


# --- HTML leak: set_body() must respect the caller's textFormat -------------


def test_set_body_plaintext_does_not_leak_markup(tmp_path):
    m = _overlay_mod()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    body = m.BodyScroll()

    body._label.setTextFormat(Qt.TextFormat.PlainText)
    body.set_body("你好。世界。", long_form=False)
    assert body._label.text() == "你好。世界。"
    assert "<" not in body._label.text()

    body._label.setTextFormat(Qt.TextFormat.RichText)
    body.set_body("**你好**", long_form=True)
    assert "<" in body._label.text()


# --- #1 single instance + session restore ------------------------------------


def test_existing_overlay_alive_matrix(tmp_path):
    m = _overlay_mod()
    # no socket file
    assert m._existing_overlay_alive(tmp_path / "none.sock") is False
    # stale socket file (no listener)
    stale = tmp_path / "stale.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(stale))
    s.close()
    assert m._existing_overlay_alive(stale) is False
    # live responder → guard fires
    live = tmp_path / "live.sock"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(live))
    srv.listen(1)

    def _serve() -> None:
        conn, _ = srv.accept()
        conn.recv(8192)
        conn.sendall(b'{"ok": true, "cmd": "ping"}\n')
        conn.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    assert m._existing_overlay_alive(live) is True
    t.join(timeout=2)
    srv.close()


def test_singleton_lock_is_atomic(tmp_path):
    m = _overlay_mod()
    sock = tmp_path / "overlay.sock"
    first = m._acquire_singleton_lock(sock)
    assert first is not None
    # Simulates the observed race: a second launcher starting the same
    # instant the first one does must not also get in.
    assert m._acquire_singleton_lock(sock) is None
    first.close()
    # Releasing (process exit, in practice) lets the next one through.
    assert m._acquire_singleton_lock(sock) is not None


def test_no_restart_sets_restart_never_hint():
    m = _overlay_mod()
    from PySide6.QtGui import QSessionManager

    class FakeSM:
        hint = None

        def setRestartHint(self, h):
            self.hint = h

    sm = FakeSM()
    m._no_restart(sm)
    assert sm.hint == QSessionManager.RestartHint.RestartNever


# --- #4 stream turn ends batch-style ------------------------------------------


def test_finish_turn_ux_done_then_followup(tmp_path, monkeypatch):
    import aipc_voice_stream as sm

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    spawned: list[list[str]] = []
    ts = sm.finish_turn_ux("最终答案。", spawn=spawned.append)
    state_p = tmp_path / "aipc-voice-state.json"
    st = json.loads(state_p.read_text(encoding="utf-8"))
    assert st["state"] == "done"
    assert st["detail"] == "最终答案。"
    assert float(st["ttl_s"]) >= 12.0  # spec: done hold ≥ 12s
    assert spawned and spawned[0][0] == sys.executable

    # decision matrix: wake's trailing listening must not cancel the follow-up
    assert sm._followup_should_write(st, ts)
    assert sm._followup_should_write({"state": "listening", "ts": ts + 3}, ts)
    assert sm._followup_should_write({"state": "muted", "ts": ts + 3}, ts)
    assert not sm._followup_should_write({"state": "thinking", "ts": ts + 3}, ts)
    assert not sm._followup_should_write({"state": "done", "ts": ts + 9}, ts)

    assert sm._followup_main([str(state_p), f"{ts:.6f}", "0", "30"]) == 0
    st2 = json.loads(state_p.read_text(encoding="utf-8"))
    assert st2["state"] == "followup" and float(st2["ttl_s"]) == 30.0

    # a newer active turn suppresses the stale follow-up write
    state_p.write_text(
        json.dumps({"state": "thinking", "ts": time.time() + 1}), encoding="utf-8"
    )
    assert sm._followup_main([str(state_p), f"{ts:.6f}", "0", "30"]) == 0
    assert json.loads(state_p.read_text(encoding="utf-8"))["state"] == "thinking"


# --- #5 no per-token ticker; text follows TTS sentences -----------------------


def test_stream_turn_overlay_states_are_sentence_driven():
    binmod = _load_source("aipc_voice_stream_bin", STREAM_BIN)

    states: list[str] = []

    class FakeUx:
        @staticmethod
        def announce(state, detail="", **kw):
            states.append(state)

    binmod.voice_ux = FakeUx
    events = [
        {"event": "session_id", "session_id": "t", "task_id": "1"},
        {"event": "token", "text": "你好。"},
        {"event": "token", "text": "世界很好。"},
        {"event": "done", "text": "你好。世界很好。", "task_id": "1"},
    ]
    ok, full = binmod.run_stream_turn(
        text="hi",
        session_id="t",
        speak=lambda t: True,
        stream_events=iter(events),
    )
    assert ok and "你好" in full
    assert "thinking" not in states  # token progress never drives the overlay
    assert "speaking" in states  # per-sentence TTS callback does
