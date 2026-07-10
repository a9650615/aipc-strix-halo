#!/usr/bin/env python3
"""Siri-like partial screen overlay for AIPC voice state.

Watches $XDG_RUNTIME_DIR/aipc-voice-state.json (written by aipc_voice_ux) and
shows a translucent always-on-top panel: orb + status + detail/transcript.

Not a full-screen modal — edges stay visible (partial overlay), Esc dismisses
the panel only (does not kill the voice pipeline).
"""
from __future__ import annotations

import json
import math
import os
import socket
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (
    QPoint,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# Any voice activity → show overlay (incl. detecting / miss feedback)
# Only intentional assistant turns — NOT ambient energy "detecting"/"miss" spam
SHOW_STATES = frozenset(
    {
        "wake",
        "recording",
        "thinking",
        "working",  # tool / Hermes progress
        "speaking",
        "followup",
        "done",  # keep panel up between multi-turn replies
        "no_speech",
        "error",
    }
)
HIDE_STATES = frozenset({"listening", "muted", "miss", "detecting"})

STATE_COLORS = {
    "listening": QColor(120, 140, 180),
    "wake": QColor(90, 200, 255),
    "recording": QColor(80, 220, 160),
    "thinking": QColor(180, 140, 255),
    "working": QColor(255, 160, 60),  # amber — tools in flight
    "speaking": QColor(100, 180, 255),
    "done": QColor(140, 140, 150),
    "followup": QColor(90, 210, 170),
    "no_speech": QColor(255, 180, 80),
    "error": QColor(255, 90, 90),
    "miss": QColor(160, 160, 160),
    "muted": QColor(100, 100, 110),
    "detecting": QColor(255, 200, 80),
}

STATE_HINTS = {
    "listening": "說「嘿助理」或按控制中心",
    "wake": "請說指令，說完停一下",
    "recording": "說完停一下就結束",
    "thinking": "辨識與回答中…",
    "working": "工具執行中，請稍候",
    "speaking": "",
    "done": "",
    "followup": "直接說下一句，無需喚醒詞",
    "no_speech": "沒聽到，請再說一次",
    "error": "出了點問題",
    "muted": "喚醒已暫停",
    "detecting": "正在辨識喚醒詞…",
    "miss": "不是喚醒詞",
}

STATE_LABELS = {
    "listening": "AIPC · 監聽中",
    "wake": "AIPC · 請說",
    "recording": "AIPC · 正在聽",
    "thinking": "AIPC · 思考中",
    "working": "AIPC · 執行中",
    "speaking": "AIPC · 回答中",
    "done": "AIPC",
    "followup": "AIPC · 可接話",
    "no_speech": "AIPC · 沒聽清",
    "error": "AIPC · 出錯",
    "muted": "AIPC · 靜音",
}


def status_path() -> Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "aipc-voice-state.json"
    return Path.home() / ".cache/aipc/voice-state.json"


def overlay_sock_path() -> Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "aipc-overlay.sock"
    return Path(f"/tmp/aipc-overlay-{os.getuid()}.sock")


def read_status() -> dict:
    p = status_path()
    if not p.is_file():
        return {"state": "listening", "detail": "", "label": "AIPC · 監聽中"}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "listening", "detail": "", "label": ""}


def write_status_payload(data: dict) -> None:
    """Persist status for file watchers (CLI / other processes)."""
    p = status_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload.setdefault("ts", time.time())
        p.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"aipc-voice-overlay: write status fail: {exc}", flush=True)


def _overlay_api_handle(req: dict, *, current: dict, visible: bool):
    """Prefer tools overlay_api; fall back to minimal inline handler."""
    try:
        from aipc_lib.overlay_api import handle_request  # type: ignore

        return handle_request(req, current=current, visible=visible)
    except Exception:
        pass
    # Minimal inline (deploy without aipc_lib on PYTHONPATH)
    cmd = str(req.get("cmd") or "").lower()
    if cmd == "ping":
        return {"ok": True, "cmd": "ping", "version": 1, "visible": visible}, []
    if cmd == "show":
        return {"ok": True, "cmd": "show"}, [{"op": "show"}]
    if cmd == "hide":
        return {"ok": True, "cmd": "hide"}, [{"op": "hide"}]
    if cmd == "raise":
        return {"ok": True, "cmd": "raise"}, [{"op": "raise"}]
    if cmd == "get":
        return {"ok": True, "cmd": "get", "status": current, "visible": visible}, []
    if cmd == "set":
        st = {
            "state": str(req.get("state") or "thinking"),
            "detail": str(req.get("detail") or ""),
            "partial": str(req.get("partial") or req.get("detail") or ""),
            "label": str(req.get("label") or ""),
            "source": str(req.get("source") or "widget"),
            "priority": int(req.get("priority") or 50),
            "ts": time.time(),
            "hint": str(req.get("hint") or ""),
        }
        return {"ok": True, "cmd": "set", "status": st}, [
            {"op": "set_status", "status": st},
            {"op": "show"},
        ]
    if cmd == "clear":
        st = {
            "state": "listening",
            "detail": "",
            "partial": "",
            "source": str(req.get("source") or "clear"),
            "priority": 0,
            "ts": time.time(),
        }
        return {"ok": True, "cmd": "clear"}, [
            {"op": "set_status", "status": st},
            {"op": "hide"},
        ]
    return {"ok": False, "error": f"unknown cmd {cmd!r}"}, []


class OverlayApiServer:
    """Unix socket control plane for other AIPC assistant widgets."""

    def __init__(self, panel: "OverlayPanel", sock_path: Path | None = None) -> None:
        self._panel = panel
        self._path = sock_path or overlay_sock_path()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending: list[tuple[dict, list]] = []  # (response unused, actions)

    def start(self) -> None:
        try:
            if self._path.exists():
                self._path.unlink()
        except OSError:
            pass
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(str(self._path))
            try:
                os.chmod(self._path, 0o666)
            except OSError:
                pass
            srv.listen(8)
            srv.settimeout(0.5)
            self._sock = srv
        except OSError as exc:
            print(f"aipc-voice-overlay: api sock bind fail: {exc}", flush=True)
            return
        self._thread = threading.Thread(target=self._loop, name="aipc-overlay-api", daemon=True)
        self._thread.start()
        print(f"aipc-voice-overlay: api sock {self._path}", flush=True)

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def drain_actions(self) -> list[dict]:
        with self._lock:
            pending = self._pending
            self._pending = []
        out: list[dict] = []
        for _resp, actions in pending:
            out.extend(actions)
        return out

    def _loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue
            try:
                self._serve_one(conn)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _serve_one(self, conn: socket.socket) -> None:
        conn.settimeout(2.0)
        buf = b""
        try:
            while b"\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > 65536:
                    break
        except OSError:
            return
        line = buf.decode("utf-8", errors="replace").strip().splitlines()
        raw = line[0] if line else ""
        try:
            if raw and raw[0] in "{[":
                req = json.loads(raw)
            else:
                # bare command
                req = {"cmd": (raw.split() or ["ping"])[0].lower()}
                if raw.lower().startswith("set ") and len(raw.split()) >= 2:
                    bits = raw.split(None, 2)
                    req = {"cmd": "set", "state": bits[1], "detail": bits[2] if len(bits) > 2 else ""}
        except (json.JSONDecodeError, ValueError) as exc:
            resp = {"ok": False, "error": str(exc)}
            try:
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            except OSError:
                pass
            return
        if not isinstance(req, dict):
            resp = {"ok": False, "error": "request must be object"}
        else:
            current = read_status()
            visible = self._panel.isVisible()
            resp, actions = _overlay_api_handle(req, current=current, visible=visible)
            if actions:
                with self._lock:
                    self._pending.append((resp, actions))
        try:
            conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError:
            pass


class OrbWidget(QWidget):
    """Pulsing orb — visual anchor like Siri waveform ball."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 56)
        self._phase = 0.0
        self._color = STATE_COLORS["listening"]
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str, active: bool) -> None:
        self._color = STATE_COLORS.get(state, STATE_COLORS["listening"])
        self._active = active
        self.update()

    def _tick(self) -> None:
        if self._active:
            self._phase += 0.12
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        base = 14.0
        pulse = (4.0 * (0.5 + 0.5 * math.sin(self._phase))) if self._active else 0.0
        r = base + pulse

        # soft outer glow
        for i, alpha in ((1.8, 30), (1.4, 55), (1.0, 200)):
            grad = QRadialGradient(cx, cy, r * i)
            c = QColor(self._color)
            c.setAlpha(alpha)
            grad.setColorAt(0.0, c)
            c2 = QColor(self._color)
            c2.setAlpha(0)
            grad.setColorAt(1.0, c2)
            p.setBrush(grad)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPoint(int(cx), int(cy)), int(r * i), int(r * i))

        # core
        core = QColor(255, 255, 255, 230 if self._active else 160)
        p.setBrush(core)
        p.setPen(QPen(self._color, 1.5))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(base * 0.45), int(base * 0.45))
        p.end()


class OverlayPanel(QWidget):
    """Top-center always-on-top HUD — never steals focus or keyboard."""

    dismissed = Signal()

    def __init__(self):
        # Prefer Window (not Tool): KDE often ignores Tool geometry and ABOVE state.
        # StaysOnTop + NoFocus + ShowWithoutActivating = HUD, not a normal app window.
        super().__init__(
            None,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("AIPC Voice")

        self._state = "listening"
        self._detail = ""
        self._label = ""
        self._hide_at: float | None = None
        self._pinned_xy: tuple[int, int] | None = None
        self._source = ""
        self._api: OverlayApiServer | None = None
        self._force_hidden = False  # API hide until next set/show

        # Layout: orb → state title → ONE primary body → optional meta hint
        # Never stack the same transcript twice (hw 2026-07-10 screenshot).
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(6)
        root.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.orb = OrbWidget()
        self.orb.setFixedSize(64, 64)
        root.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignHCenter)

        self.title = QLabel("AIPC")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet("color: #f4f6fa; letter-spacing: 0.2px;")
        root.addWidget(self.title)

        # Primary: live transcript (recording) or reply/progress (thinking/speaking)
        self.primary = QLabel("")
        self.primary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.primary.setWordWrap(True)
        self.primary.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.primary.setStyleSheet(
            "color: #e8edf5; font-size: 13px; font-weight: 500; line-height: 1.35;"
        )
        self.primary.setMinimumWidth(220)
        self.primary.setMaximumWidth(320)
        root.addWidget(self.primary)

        # Meta: short static instruction only when primary is empty / different
        self.meta = QLabel("")
        self.meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meta.setWordWrap(True)
        self.meta.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.meta.setStyleSheet("color: #8b97a8; font-size: 11px;")
        self.meta.setMinimumWidth(200)
        self.meta.setMaximumWidth(300)
        root.addWidget(self.meta)

        # Back-compat aliases (older call sites / tests)
        self.hint = self.meta
        self.detail = self.primary

        self.setFixedWidth(300)
        self.adjustSize()

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._on_poll)
        self._poll.start(200)

        # Re-pin top-center + reassert stay-on-top (KDE can bury/recenter windows)
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._place_and_raise)
        self._pos_timer.start(800)

        # Widget control API (Unix sock) — polled into Qt thread via _on_poll
        self._api = OverlayApiServer(self)
        self._api.start()

        self.hide()
        self._on_poll()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        # glass card
        bg = QColor(14, 18, 26, 220)
        p.fillPath(path, bg)
        pen = QPen(QColor(255, 255, 255, 42))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)
        # top sheen
        sheen = QColor(255, 255, 255, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(sheen)
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -rect.height() * 0.55), 18, 18)
        p.end()

    def _show_passive(self) -> None:
        """Show without activating; keep above other windows (no focus steal)."""
        self._place_and_raise()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.show()
        self._raise_top()

    def _raise_top(self) -> None:
        """Keep HUD above normal windows (no activate — don't steal focus)."""
        if not self.isVisible():
            return
        self.raise_()
        wh = self.windowHandle()
        if wh is not None:
            try:
                wh.raise_()
            except Exception:
                pass

    def _target_screen(self):
        """Screen under pointer (active display), else primary."""
        try:
            sc = QGuiApplication.screenAt(QCursor.pos())
            if sc is not None:
                return sc
        except Exception:
            pass
        return QGuiApplication.primaryScreen()

    def _place(self) -> None:
        """Pin to top-center of the active screen (assistant HUD).

        KDE/Plasma sometimes recenters frameless windows if we only call move()
        once. We use full screen geometry (not availableGeometry center) for Y
        so the HUD sits near the top edge, not mid-screen.
        """
        screen = self._target_screen()
        if not screen:
            return
        # availableGeometry excludes panels — use it for X bounds; for Y prefer
        # the top of available area so we sit just under the panel, not center.
        avail = screen.availableGeometry()
        full = screen.geometry()
        self.adjustSize()
        w, h = self.width(), self.height()
        margin_y = int(os.environ.get("AIPC_OVERLAY_MARGIN_Y", "12"))
        anchor = (os.environ.get("AIPC_OVERLAY_ANCHOR") or "top-center").strip().lower()
        if anchor in ("top-right", "right"):
            margin_x = int(os.environ.get("AIPC_OVERLAY_MARGIN_X", "12"))
            x = int(avail.right() - w - margin_x)
        else:
            x = int(avail.left() + (avail.width() - w) / 2)
        # Top of work area (below panel) — never vertical center of the screen
        y = int(avail.top() + margin_y)
        # Safety: if availableGeometry is broken (top near mid-screen), fall back
        if y > full.top() + full.height() // 4:
            y = int(full.top() + margin_y)
        self.setFixedSize(w, h)
        self.setGeometry(x, y, w, h)
        self.move(x, y)
        wh = self.windowHandle()
        if wh is not None:
            try:
                wh.setFramePosition(QPoint(x, y))
            except Exception:
                try:
                    wh.setPosition(x, y)
                except Exception:
                    pass
        # KDE often ignores the first move — re-apply a few times
        if self.isVisible():
            for delay in (0, 16, 50, 120):
                QTimer.singleShot(
                    delay,
                    lambda xx=x, yy=y, ww=w, hh=h: (
                        self.setGeometry(xx, yy, ww, hh),
                        self.move(xx, yy),
                    ),
                )
        self._pinned_xy = (x, y)
        if os.environ.get("AIPC_OVERLAY_DEBUG"):
            try:
                logp = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "aipc-overlay-place.log"
                with logp.open("a", encoding="utf-8") as lf:
                    lf.write(
                        f"screen={screen.name()} anchor={anchor} "
                        f"avail=({avail.x()},{avail.y()} {avail.width()}x{avail.height()}) "
                        f"→ ({x},{y}) size={w}x{h} actual=({self.x()},{self.y()})\n"
                    )
            except OSError:
                pass

    def _place_and_raise(self) -> None:
        self._place()
        if self.isVisible():
            self._raise_top()
            QTimer.singleShot(40, self._place)
            QTimer.singleShot(40, self._raise_top)

    @staticmethod
    def _norm_ui(s: str) -> str:
        return " ".join((s or "").split()).strip()

    def _pick_primary(self, state: str, detail: str, partial: str) -> str:
        """One body line: live STT while listening; answer/progress otherwise."""
        d = self._norm_ui(detail)
        p = self._norm_ui(partial)
        static = self._norm_ui(STATE_HINTS.get(state, ""))
        # Strip accidental duplication of static hints into content fields
        if d and static and (d == static or d.startswith(static[:8])):
            d = ""
        if state in ("recording", "followup", "wake"):
            # Prefer live partial; detail only if it is not a static cue
            body = p or d
        elif state in ("thinking", "working", "speaking", "error", "no_speech", "miss"):
            body = d or p
        else:
            body = d or p
        if body in ("…", ".", "。"):
            return ""
        return body

    def _pick_meta(self, state: str, primary: str, hint_field: str) -> str:
        """Secondary line: short cue only when it adds info beyond primary."""
        static = self._norm_ui(STATE_HINTS.get(state, ""))
        hint_field = self._norm_ui(hint_field)
        # Prefer curated static over free-form hint when recording/speaking
        cand = static or hint_field
        if not cand:
            return ""
        if primary and (
            cand == primary
            or primary.startswith(cand)
            or cand.startswith(primary)
            or cand in primary
            or primary in cand
        ):
            return ""
        # With a live transcript, do not also show "正在聽…" style noise
        if primary and state in ("recording", "speaking", "thinking", "working"):
            return ""
        return cand

    def apply_status(self, data: dict) -> None:
        state = str(data.get("state") or "listening")
        detail = str(data.get("detail") or "")
        partial = str(data.get("partial") or "")
        label = str(data.get("label") or "")
        source = str(data.get("source") or "")
        hint_field = str(data.get("hint") or "")
        self._state = state
        self._detail = detail or partial
        self._label = label
        self._source = source

        active = state in SHOW_STATES
        self.orb.set_state(state, active=active and state != "error")

        # Title = state only (never put transcript in the title row)
        title = label or STATE_LABELS.get(state) or f"AIPC · {state}"
        # Avoid labels that already embed a long detail
        if len(title) > 28:
            title = STATE_LABELS.get(state) or "AIPC"
        self.title.setText(title)

        primary = self._pick_primary(state, detail, partial)
        meta = self._pick_meta(state, primary, hint_field)

        if primary:
            shown = primary if len(primary) <= 96 else primary[:93] + "…"
            self.primary.setText(shown)
            self.primary.show()
        else:
            self.primary.setText("")
            self.primary.hide()

        if meta:
            self.meta.setText(meta)
            self.meta.show()
        else:
            self.meta.setText("")
            self.meta.hide()

        self.adjustSize()

        if state in SHOW_STATES:
            self._show_passive()
            # Active conversation states: never auto-hide (user may still be talking).
            if state in ("wake", "recording", "thinking", "working", "speaking", "followup"):
                self._hide_at = None
            elif state == "done":
                # Brief hold between turns; followup should replace this quickly.
                self._hide_at = time.time() + 4.0
            elif state == "no_speech":
                # Brief flash then gone — do not sit on "没听清"
                self._hide_at = time.time() + 1.0
            elif state in ("detecting", "miss"):
                self._hide_at = time.time() + (2.8 if state == "miss" else 2.0)
            else:
                self._hide_at = None
        elif state in HIDE_STATES:
            if state == "listening":
                # End of 接话 / idle: disappear quickly (was 2.5s linger)
                self._hide_at = time.time() + 0.25
            elif state == "muted":
                self._hide_at = time.time() + 1.2
            else:
                self._hide_at = time.time() + 1.0
            self._place()
        else:
            # Unknown custom state from widget API → still show card
            self._show_passive()
            self._hide_at = time.time() + float(data.get("ttl_s") or 8.0)

    def _apply_api_actions(self, actions: list[dict]) -> None:
        for act in actions:
            op = act.get("op")
            if op == "show":
                self._force_hidden = False
                self._show_passive()
                self._hide_at = None
            elif op == "hide":
                self._force_hidden = True
                self.hide()
                self._hide_at = None
            elif op == "raise":
                self._force_hidden = False
                if self.isVisible():
                    self._raise_top()
                else:
                    self._show_passive()
            elif op == "set_status":
                self._force_hidden = False
                st = dict(act.get("status") or {})
                write_status_payload(st)
                self.apply_status(st)
                self._last_key = (
                    st.get("state"),
                    st.get("detail"),
                    st.get("partial"),
                    st.get("label"),
                    st.get("hint"),
                    st.get("ts"),
                    st.get("source"),
                )

    def _on_poll(self) -> None:
        # Widget API actions first (authoritative for that client)
        if self._api is not None:
            acts = self._api.drain_actions()
            if acts:
                self._apply_api_actions(acts)

        if self._force_hidden:
            if self.isVisible():
                self.hide()
            return

        data = read_status()
        # only re-apply when changed enough
        key = (
            data.get("state"),
            data.get("detail"),
            data.get("partial"),
            data.get("label"),
            data.get("hint"),
            data.get("ts"),
            data.get("source"),
        )
        if getattr(self, "_last_key", None) != key:
            self._last_key = key
            self.apply_status(data)
        if self._hide_at is not None and time.time() >= self._hide_at:
            self.hide()
            self._hide_at = None
        elif self.isVisible():
            # Stay on top while conversation HUD is up
            self._raise_top()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # HiDPI
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    # Wayland ignores QWidget.move() for Tool windows → appear centered.
    # Prefer XWayland (xcb) so top-right pin works under KDE Wayland.
    if os.environ.get("AIPC_OVERLAY_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = os.environ["AIPC_OVERLAY_PLATFORM"]
    elif os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    app = QApplication(argv)
    app.setApplicationName("aipc-voice-overlay")
    app.setQuitOnLastWindowClosed(False)

    panel = OverlayPanel()

    def _cleanup() -> None:
        if panel._api is not None:
            panel._api.stop()

    app.aboutToQuit.connect(_cleanup)
    # keep process alive
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
