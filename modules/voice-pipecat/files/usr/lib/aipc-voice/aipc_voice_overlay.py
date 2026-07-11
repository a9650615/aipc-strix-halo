#!/usr/bin/env python3
"""Siri-like partial screen overlay for AIPC voice / agent state.

Watches $XDG_RUNTIME_DIR/aipc-voice-state.json and the control socket.
Shows a glass HUD: orb + title + long-form scrollable body + meta.

Goals (2026-07-10+):
  - Long answers fully readable (scroll, not 96-char cut)
  - Premium glass card + state accent + smooth fade / size motion
  - Replaces native notify-send for day-to-day replies
"""
from __future__ import annotations

import json
import math
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl

# Intentional assistant turns — not ambient "detecting"/"miss" spam
SHOW_STATES = frozenset(
    {
        "wake",
        "recording",
        "thinking",
        "working",
        "speaking",
        "followup",
        "done",
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
    "working": QColor(255, 160, 60),
    "speaking": QColor(100, 180, 255),
    "done": QColor(120, 200, 170),
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
    "done": "可滾動閱讀 · 說「不对」可反饋",
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
    "done": "AIPC · 已回答",
    "followup": "AIPC · 可接話",
    "no_speech": "AIPC · 沒聽清",
    "error": "AIPC · 出錯",
    "muted": "AIPC · 靜音",
}

_ELAPSED_TAIL_RE = __import__("re").compile(
    r"(?:[（(]\s*(?:已\s*)?\d+\s*s\s*[）)]|\s*[·•]\s*\d+\s*s)\s*$",
    __import__("re").IGNORECASE,
)


def _strip_elapsed(text: str) -> str:
    """Ignore pure timer tails so working ticks don't reflow layout."""
    return _ELAPSED_TAIL_RE.sub("", (text or "").strip()).strip()


def _mini_chip_label(detail: str) -> str:
    """Readable mini label; width is sized from measured text, not a fixed clip."""
    raw = (detail or "").strip()
    sec = ""
    m = __import__("re").search(r"(\d+)\s*s", raw, __import__("re").I)
    if m:
        sec = m.group(1)
    # Prefer short phase words; keep seconds
    low = raw.lower()
    if any(k in raw for k in ("搜尋", "搜索", "search")):
        phase = "搜尋中"
    elif any(k in raw or k in low for k in ("瀏覽", "browser", "網頁")):
        phase = "瀏覽中"
    elif any(k in raw for k in ("整理", "結果")):
        phase = "整理中"
    elif any(k in raw for k in ("思考", "thinking")):
        phase = "思考中"
    elif "hermes" in low or "Hermes" in raw or "工具" in raw:
        phase = "工具執行中"
    else:
        phase = "執行中"
    return f"{phase} · {sec}s" if sec else phase


def _luma(c: QColor) -> float:
    """Relative luminance 0..1 (sRGB approx)."""
    r, g, b = c.redF(), c.greenF(), c.blueF()

    def _lin(u: float) -> float:
        return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_text_on(bg: QColor) -> QColor:
    """Pick light or dark text for readable contrast on bg."""
    # Dark glass → near-white; if ever light glass → near-black
    if _luma(bg) < 0.45:
        return QColor(238, 242, 248, 255)  # #eef2f8
    return QColor(18, 22, 30, 255)


def _contrast_muted_on(bg: QColor) -> QColor:
    base = _contrast_text_on(bg)
    base.setAlpha(170 if _luma(bg) < 0.45 else 160)
    return base


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
    cmd = str(req.get("cmd") or "").lower()
    if cmd == "ping":
        return {"ok": True, "cmd": "ping", "version": 2, "visible": visible}, []
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
        for k in ("ttl_s", "hold_s"):
            if req.get(k) is not None:
                try:
                    st[k] = float(req[k])
                except (TypeError, ValueError):
                    pass
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
        self._pending: list[tuple[dict, list]] = []

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
        self._thread = threading.Thread(
            target=self._loop, name="aipc-overlay-api", daemon=True
        )
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
                chunk = conn.recv(8192)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > 262144:
                    break
        except OSError:
            return
        line = buf.decode("utf-8", errors="replace").strip().splitlines()
        raw = line[0] if line else ""
        try:
            if raw and raw[0] in "{[":
                req = json.loads(raw)
            else:
                req = {"cmd": (raw.split() or ["ping"])[0].lower()}
                if raw.lower().startswith("set ") and len(raw.split()) >= 2:
                    bits = raw.split(None, 2)
                    req = {
                        "cmd": "set",
                        "state": bits[1],
                        "detail": bits[2] if len(bits) > 2 else "",
                    }
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
    """Multi-ring pulse orb — visual anchor (scales for mini / full HUD)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._color = STATE_COLORS["listening"]
        self._active = False
        self._base_r = 16.0
        self.set_orb_size(72)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)  # ~60fps when active; cheap when idle

    def set_orb_size(self, px: int, *, animate: bool = False) -> None:
        """Snap size (no tween). Animated orb size reflows the card and causes layout twitch."""
        px = max(28, min(int(px), 88))
        if abs(self.width() - px) <= 0:
            return
        self.setFixedSize(px, px)
        self._base_r = max(8.0, px * 0.22)
        self.update()

    def set_state(self, state: str, active: bool) -> None:
        self._color = STATE_COLORS.get(state, STATE_COLORS["listening"])
        self._active = active
        # spin a bit faster on active tool runs
        self._spin = 0.11 if active and state in ("working", "thinking") else 0.08
        self.update()

    def _tick(self) -> None:
        # Always breathe a little when visible; stronger when active
        spin = getattr(self, "_spin", 0.08)
        if self._active:
            self._phase += spin
            self.update()
        elif self.isVisible():
            self._phase += 0.03
            if int(self._phase * 10) % 3 == 0:
                self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        base = self._base_r
        breath = (0.5 + 0.5 * math.sin(self._phase)) if self._active else (
            0.35 + 0.15 * math.sin(self._phase * 0.7)
        )
        pulse = (base * 0.38) * breath
        r = base + pulse

        # rotating accent arc (activity cue)
        if self._active:
            p.save()
            p.translate(cx, cy)
            p.rotate((self._phase * 48) % 360)
            pen_arc = QPen(QColor(self._color.red(), self._color.green(), self._color.blue(), 160))
            pen_arc.setWidthF(max(1.5, base * 0.12))
            pen_arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen_arc)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rr = r * 1.55
            p.drawArc(QRectF(-rr, -rr, rr * 2, rr * 2), 30 * 16, 110 * 16)
            p.restore()

        # outer halo rings
        for i, (scale, alpha) in enumerate(((2.15, 18), (1.7, 36), (1.35, 70), (1.0, 160))):
            grad = QRadialGradient(cx, cy, r * scale)
            c = QColor(self._color)
            a = int(alpha * (0.75 + 0.25 * math.sin(self._phase + i * 0.7)))
            c.setAlpha(max(8, a) if self._active else max(6, alpha // 3))
            grad.setColorAt(0.0, c)
            c2 = QColor(self._color)
            c2.setAlpha(0)
            grad.setColorAt(1.0, c2)
            p.setBrush(grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPoint(int(cx), int(cy)), int(r * scale), int(r * scale))

        # glass core
        core = QRadialGradient(cx - 2, cy - 2, base * 0.7)
        core.setColorAt(0.0, QColor(255, 255, 255, 245 if self._active else 190))
        core.setColorAt(0.55, QColor(240, 245, 255, 210 if self._active else 150))
        core.setColorAt(1.0, QColor(self._color.red(), self._color.green(), self._color.blue(), 90))
        p.setBrush(core)
        p.setPen(QPen(QColor(self._color.red(), self._color.green(), self._color.blue(), 180), 1.4))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(base * 0.48), int(base * 0.48))
        p.end()


def _extract_image_urls(text: str, *, limit: int = 6) -> list[str]:
    """Collect likely raster image URLs from answer text (any topic)."""
    import re

    urls = re.findall(r"https?://[^\s\]\)\"'<>，。、]+", text or "", flags=re.I)
    out: list[str] = []
    skip = (
        "processing.jpg",
        "placeholder",
        "1x1",
        "pixel.gif",
        "favicon",
        "logo.svg",
        "sprite",
    )
    for u in urls:
        u = u.rstrip(".,;:)")
        low = u.lower()
        if any(s in low for s in skip):
            continue
        if re.search(r"\.(png|jpe?g|gif|webp|bmp)(?:\?|$)", low):
            if u not in out:
                out.append(u)
        # Some CDNs omit extension but path says image
        elif re.search(r"/(image|images|img|media|photo|thumb|chart|map)s?/", low):
            if u not in out and "html" not in low.split("?")[0][-8:]:
                out.append(u)
        if len(out) >= limit:
            break
    return out


_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?[^)]*\)")


def _extract_and_strip_media(text, extra=None):
    """Return (text_without_image_refs, ordered_unique_image_urls).

    Pulls markdown ![](url) and bare image URLs so they render in the safe
    gallery instead of as raw text. Non-image links are left in the text.
    """
    s = text or ""
    urls: list[str] = []

    def _add(u: str) -> None:
        u = (u or "").strip().strip("<>")
        if u and u not in urls:
            urls.append(u)

    for u in extra or []:
        _add(u)

    def _sub(m: "re.Match") -> str:
        _add(m.group(1))
        return ""

    s = _MD_IMG_RE.sub(_sub, s)
    for u in _extract_image_urls(re.sub(r"<[^>]+>", " ", s)):
        _add(u)
    for u in urls:
        s = s.replace(u, "")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s, urls


def _markdown_to_html(text):
    """Markdown → Qt rich-text HTML via QTextDocument (built into PySide6).

    Falls back to escaped plain text on empty/parse failure — never raises.
    """
    s = (text or "").strip()
    if not s:
        return ""
    try:
        from PySide6.QtGui import QTextDocument

        doc = QTextDocument()
        doc.setMarkdown(s)
        html = doc.toHtml()
        if html and "<" in html:
            return html
    except Exception:
        pass
    import html as _h

    return _h.escape(s).replace("\n", "<br>")


def _source_host(url):
    """Bare host for a URL caption (drops www.), '' on failure."""
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


class _ImageFetch(QObject):
    """Background HTTP fetch → main-thread pixmap (no Qt Network dependency)."""

    finished = Signal(int, str, bytes)  # gen, url, data
    failed = Signal(int, str, str)  # gen, url, err

    def fetch(self, gen: int, url: str, timeout: float = 12.0) -> None:
        def _run() -> None:
            try:
                import ssl
                import urllib.error
                import urllib.request

                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                }
                # Referer helps some gov CDNs
                try:
                    from urllib.parse import urlparse

                    p = urlparse(url)
                    if p.scheme and p.netloc:
                        headers["Referer"] = f"{p.scheme}://{p.netloc}/"
                except Exception:
                    pass
                req = urllib.request.Request(url, headers=headers, method="GET")

                def _read(ctx=None) -> bytes:
                    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                        return resp.read()

                try:
                    data = _read(None)
                except (urllib.error.URLError, ssl.SSLError):
                    # Some hosts (e.g. cwa.gov.tw) fail system cert chain on this box
                    data = _read(ssl._create_unverified_context())
                if not data or len(data) < 32:
                    self.failed.emit(gen, url, "empty")
                    return
                # hard cap ~8MB
                if len(data) > 8_000_000:
                    self.failed.emit(gen, url, "too large")
                    return
                # Reject obvious HTML error pages
                head = data[:200].lstrip().lower()
                if head.startswith(b"<!doctype") or head.startswith(b"<html"):
                    self.failed.emit(gen, url, "html not image")
                    return
                self.finished.emit(gen, url, data)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(gen, url, str(exc)[:120])

        threading.Thread(target=_run, name="overlay-img", daemon=True).start()


class BodyScroll(QScrollArea):
    """Scrollable answer body: text + rendered image gallery.

    widgetResizable stays False so content height drives the scrollbar.
    """

    images_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            """
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: rgba(255,255,255,12);
                width: 8px;
                margin: 2px 1px 2px 0;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,90);
                border-radius: 4px;
                min-height: 32px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255,255,255,140);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
            """
        )
        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._v = QVBoxLayout(self._inner)
        self._v.setContentsMargins(0, 0, 0, 0)
        self._v.setSpacing(8)

        self._label = QLabel("")
        self._label.setTextFormat(Qt.TextFormat.RichText)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._label.setOpenExternalLinks(True)
        self._label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum
        )
        self._v.addWidget(self._label, 0, Qt.AlignmentFlag.AlignTop)

        self._gallery = QWidget()
        self._gallery.setStyleSheet("background: transparent;")
        self._gal = QGridLayout(self._gallery)
        self._gal.setContentsMargins(0, 4, 0, 0)
        self._gal.setSpacing(8)
        self._gal_cols = 1
        self._gal_cell_w = 0
        self._v.addWidget(self._gallery, 0, Qt.AlignmentFlag.AlignTop)
        self._v.addStretch(0)

        self.setWidget(self._inner)
        self._content_h = 0
        self._inner_w = 200
        self._img_labels: list[QLabel] = []
        self._img_urls: list[str] = []
        self._load_gen = 0
        self._fetcher = _ImageFetch()
        self._fetcher.finished.connect(self._on_img_ok)
        self._fetcher.failed.connect(self._on_img_fail)
        self._max_img_h = 200
        self._max_imgs = 4

    def set_body(
        self,
        text: str,
        *,
        long_form: bool,
        width: int = 0,
        font_px: float = 13.5,
        font_weight: int = 450,
        color: str = "#eef2f8",
        line_height: float = 1.45,
        image_urls: list[str] | None = None,
    ) -> int:
        """Set text + optional images; return full content height."""
        px = max(11.0, min(18.0, float(font_px)))
        wt = max(300, min(700, int(font_weight)))
        lh = max(1.25, min(1.6, float(line_height)))
        if long_form:
            self._label.setAlignment(
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
            )
            pad = "2px 6px 6px 2px"
        else:
            self._label.setAlignment(
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
            )
            pad = "0 2px"
        self._label.setStyleSheet(
            f"color: {color}; font-size: {px:.1f}px; font-weight: {wt}; "
            f"line-height: {lh:.2f}; padding: {pad}; background: transparent;"
        )
        f = self._label.font()
        f.setPixelSize(max(11, int(round(px))))
        f.setWeight(QFont.Weight.Medium if wt >= 500 else QFont.Weight.Normal)
        self._label.setFont(f)
        # Markdown text + safe media extraction: image URLs go to the gallery,
        # non-image links stay in the rendered text.
        clean, urls = _extract_and_strip_media(text or "", image_urls)
        self._label.setText(_markdown_to_html(clean))
        self.set_images(urls, width=width)
        return self.measure_content_height(width)

    def clear_images(self) -> None:
        self._load_gen += 1
        while self._gal.count():
            item = self._gal.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._img_labels.clear()
        self._img_urls.clear()

    def set_images(self, urls: list[str], *, width: int = 0) -> None:
        """Async-load and display image URLs (max N)."""
        self.clear_images()
        if not urls:
            self._gallery.hide()
            return
        try:
            max_n = int(os.environ.get("AIPC_OVERLAY_MAX_IMAGES", "4"))
        except ValueError:
            max_n = 4
        try:
            self._max_img_h = int(os.environ.get("AIPC_OVERLAY_IMAGE_MAX_H", "220"))
        except ValueError:
            self._max_img_h = 220
        max_n = max(1, min(8, max_n))
        w = int(width) if width > 0 else self._inner_w
        w = max(120, w - 8)
        gen = self._load_gen
        self._gallery.show()
        items = urls[:max_n]
        # 2-up grid when there is more than one image; single column otherwise.
        cols = 2 if len(items) > 1 else 1
        cell_w = max(120, (w - (cols - 1) * 8) // cols)
        self._gal_cols = cols
        self._gal_cell_w = cell_w
        for i, url in enumerate(items):
            lab = QLabel("🖼 載入中…")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setWordWrap(True)
            lab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lab.setStyleSheet(
                "color: #9aa8bc; background: rgba(255,255,255,10); "
                "border: 1px solid rgba(255,255,255,28); border-radius: 10px; "
                "padding: 10px; font-size: 12px;"
            )
            lab.setFixedWidth(cell_w)
            lab.setMinimumHeight(56)
            lab.setCursor(Qt.CursorShape.PointingHandCursor)
            lab.setProperty("img_url", url)
            host = _source_host(url)
            lab.setToolTip(f"{host}\n{url}" if host else url)
            lab.mousePressEvent = (  # type: ignore[method-assign]
                lambda ev, u=url: QDesktopServices.openUrl(QUrl(u))
            )
            self._gal.addWidget(lab, i // cols, i % cols)
            self._img_labels.append(lab)
            self._img_urls.append(url)
            self._fetcher.fetch(gen, url)
        self.measure_content_height(w + 10)

    def _on_img_ok(self, gen: int, url: str, data: bytes) -> None:
        if gen != self._load_gen:
            return
        try:
            idx = self._img_urls.index(url)
        except ValueError:
            return
        lab = self._img_labels[idx]
        pm = QPixmap()
        if not pm.loadFromData(data):
            lab.setText("⚠ 無法解碼圖片")
            return
        w = max(100, self._gal_cell_w or lab.width() or self._inner_w)
        # Fit width, cap height
        scaled = pm.scaled(
            w,
            self._max_img_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        lab.setPixmap(scaled)
        lab.setFixedSize(w, scaled.height() + 4)
        lab.setStyleSheet(
            "background: rgba(0,0,0,40); border: 1px solid rgba(255,255,255,35); "
            "border-radius: 10px; padding: 2px;"
        )
        lab.setToolTip(url)
        self.measure_content_height(self._inner_w)
        self.images_changed.emit()

    def _on_img_fail(self, gen: int, url: str, err: str) -> None:
        if gen != self._load_gen:
            return
        try:
            idx = self._img_urls.index(url)
        except ValueError:
            return
        lab = self._img_labels[idx]
        short = url if len(url) < 48 else url[:45] + "…"
        lab.setText(f"連結（載入失敗）\n{short}")
        lab.setMinimumHeight(48)
        # still clickable via mousePressEvent
        self.measure_content_height(self._inner_w)
        self.images_changed.emit()

    def measure_content_height(self, width: int = 0) -> int:
        """Height of text + image gallery at the given width."""
        w = int(width) if width > 0 else max(80, self.viewport().width() or 200)
        w = max(80, w - 10)
        self._inner_w = w
        text_h = 0
        if (self._label.text() or "").strip():
            self._label.setFixedWidth(w)
            h = self._label.heightForWidth(w)
            if h is None or h < 8:
                self._label.adjustSize()
                h = max(self._label.sizeHint().height(), 20)
            text_h = int(h) + 6
            self._label.setFixedSize(w, text_h)
        else:
            self._label.setFixedSize(w, 0)

        gal_h = 0
        if self._img_labels:
            cols = max(1, self._gal_cols)
            cell_w = self._gal_cell_w or w
            row_h = 0
            for i, lab in enumerate(self._img_labels):
                lab.setFixedWidth(cell_w)
                if lab.pixmap() is not None and not lab.pixmap().isNull():
                    lh = lab.height()
                else:
                    lh = max(56, lab.minimumHeight())
                row_h = max(row_h, lh)
                if i % cols == cols - 1:
                    gal_h += row_h + 8
                    row_h = 0
            if row_h:
                gal_h += row_h + 8
            self._gallery.setFixedWidth(w)
            self._gallery.setFixedHeight(max(0, gal_h))
            self._gallery.show()
        else:
            self._gallery.setFixedHeight(0)
            self._gallery.hide()

        total = text_h + (gal_h if self._img_labels else 0) + 4
        self._content_h = total
        self._inner.setFixedSize(w + 4, max(total, 1))
        return total

    def fit_viewport(self, max_h: int, *, min_h: int = 24) -> int:
        """Set scroll viewport height: grow with content, cap at max_h (then scroll)."""
        content = max(0, self._content_h)
        if content <= 0:
            self.setFixedHeight(0)
            return 0
        # When images present, allow a taller viewport
        if self._img_labels:
            max_h = max(max_h, min(420, max_h + 160))
        view_h = max(min_h, min(content, max(min_h, int(max_h))))
        self.setFixedHeight(view_h)
        if content > view_h + 2:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().setValue(0)
        return view_h

    def body_text(self) -> str:
        return self._label.text()


class OverlayPanel(QWidget):
    """Top-center always-on-top glass HUD — never steals focus or keyboard."""

    dismissed = Signal()

    def __init__(self):
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
        self._force_hidden = False
        self._accent = STATE_COLORS["listening"]
        self._card_w = 420
        self._fading_out = False
        self._opacity_anim: QPropertyAnimation | None = None
        self._geom_anim: QPropertyAnimation | None = None
        self._anim_group: QParallelAnimationGroup | None = None
        self._target_h = 120
        self._last_geom: tuple[int, int, int, int] | None = None
        self._last_place_t = 0.0
        self._last_state = ""
        self._soft_text_only = False
        self._body_len = 0
        self._long_form = False
        self._mini = False
        self._content_h = 0
        self._view_h = 0
        self._base_y: int | None = None
        self._animating_geom = False
        self._layout_key: tuple | None = None  # freeze geom when key unchanged
        self._last_shown: str = ""
        self._locked_geom: tuple[int, int, int, int] | None = None
        self._text_w: int = 0  # measured title/body text width for dynamic sizing
        self._bg_color = QColor(14, 18, 28, 236)
        self._fg_color = _contrast_text_on(self._bg_color)
        self._fg_muted = _contrast_muted_on(self._bg_color)

        # Full: vertical orb → title → body → meta
        # Mini: horizontal chip (orb | short label) so text never overflows glass
        root = QVBoxLayout(self)
        self._root = root
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(6)
        root.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.orb = OrbWidget()
        self.title = QLabel("AIPC")
        self.title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.title.setWordWrap(False)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        self.title.setFont(f)
        self.title.setStyleSheet("color: #f4f6fa; background: transparent;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.body = BodyScroll()
        self.body.setMinimumHeight(0)
        self.body.images_changed.connect(self._on_body_images_changed)

        self.meta = QLabel("")
        self.meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meta.setWordWrap(True)
        self.meta.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.meta.setStyleSheet(
            "color: #8b97a8; font-size: 11px; background: transparent; padding-top: 2px;"
        )

        # mini chip container (built on demand in _set_chrome)
        self._chip_row: QWidget | None = None
        self._chip_layout: QHBoxLayout | None = None
        self._layout_mode: str = ""  # "mini" | "full"
        self._apply_layout_mode("full")

        # back-compat aliases
        self.hint = self.meta
        self.primary = self.body._label
        self.detail = self.body._label

        self._apply_card_width(body_len=0, long_form=False)
        self.setWindowOpacity(0.0)

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._on_poll)
        self._poll.start(200)

        # Raise only — never re-layout (re-place was a major twitch source)
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._raise_top)
        self._pos_timer.start(4000)

        self._api = OverlayApiServer(self)
        self._api.start()

        self.hide()
        self._on_poll()

    def _screen_metrics(self) -> tuple[int, int]:
        screen = self._target_screen()
        if not screen:
            return 1600, 900
        g = screen.availableGeometry()
        return g.width(), g.height()

    def _measure_text_width(self, text: str, *, font: QFont | None = None) -> int:
        """Pixel width of a single line (for dynamic card / chip sizing)."""
        f = font or self.title.font()
        fm = QFontMetrics(f)
        s = (text or "").replace("\n", " ")
        # horizontalAdvance is accurate for CJK + Latin
        return int(fm.horizontalAdvance(s))

    def _body_typography(self, body_len: int, *, long_form: bool) -> dict:
        """Dynamic type scale from content length (short = larger/brighter).

        User request: text brightness / size tracks content, not only box layout.
        """
        n = max(0, int(body_len))
        if n <= 0:
            return {"px": 13.0, "weight": 500, "lh": 1.40}
        if n < 28:
            return {"px": 16.5, "weight": 560, "lh": 1.32}
        if n < 56:
            return {"px": 15.5, "weight": 520, "lh": 1.36}
        if n < 100:
            return {"px": 14.5, "weight": 500, "lh": 1.40}
        if n < 200:
            return {"px": 14.0, "weight": 450, "lh": 1.42}
        if n < 420 or long_form:
            return {"px": 13.5, "weight": 450, "lh": 1.45}
        return {"px": 13.0, "weight": 400, "lh": 1.48}

    def _apply_text_contrast(self, *, body_len: int = 0) -> None:
        """Dynamic text brightness: contrast against glass bg + content scale."""
        # Sample effective bg (mini slightly darker fill)
        if self._mini:
            bg = QColor(15, 19, 28, 248)
        else:
            bg = QColor(14, 18, 28, 236)
        # Accent-tinted bg average for contrast (state color bleeds a little)
        acc = QColor(self._accent)
        bg = QColor(
            int(bg.red() * 0.92 + acc.red() * 0.08),
            int(bg.green() * 0.92 + acc.green() * 0.08),
            int(bg.blue() * 0.92 + acc.blue() * 0.08),
            255,
        )
        self._bg_color = bg
        self._fg_color = _contrast_text_on(bg)
        self._fg_muted = _contrast_muted_on(bg)
        fg = self._fg_color.name()
        mu = self._fg_muted.name()
        # Short answers: lift luminance slightly for "bright" punch
        if not self._mini and 0 < body_len < 56:
            c = QColor(self._fg_color)
            c = QColor(
                min(255, int(c.red() * 1.06 + 8)),
                min(255, int(c.green() * 1.06 + 8)),
                min(255, int(c.blue() * 1.05 + 6)),
            )
            fg = c.name()
        if self._mini:
            self.title.setStyleSheet(
                f"color: {fg}; background: transparent; font-weight: 600; "
                "padding: 0; margin: 0;"
            )
        else:
            # Title scales mildly with body
            t_px = 13 if body_len >= 200 else (14 if body_len >= 56 else 15)
            self.title.setStyleSheet(
                f"color: {fg}; background: transparent; font-size: {t_px}px; "
                f"font-weight: 650;"
            )
            self.meta.setStyleSheet(
                f"color: {mu}; font-size: 11px; background: transparent; padding-top: 2px;"
            )
            try:
                ty = self._body_typography(body_len, long_form=bool(self._long_form))
                pad = (
                    "2px 6px 6px 2px"
                    if self._long_form
                    else "0 2px"
                )
                self.body._label.setStyleSheet(
                    f"color: {fg}; font-size: {ty['px']:.1f}px; font-weight: {ty['weight']}; "
                    f"line-height: {ty['lh']:.2f}; padding: {pad}; background: transparent;"
                )
            except Exception:
                pass

    def _desired_card_width(
        self,
        *,
        body_len: int = 0,
        long_form: bool = False,
        mini: bool = False,
        text: str = "",
        body_text: str = "",
    ) -> int:
        """Continuous width from measured text — not only coarse length buckets."""
        sw, _sh = self._screen_metrics()
        try:
            env_w = int(os.environ.get("AIPC_OVERLAY_WIDTH", "0") or "0")
        except ValueError:
            env_w = 0
        if env_w > 0:
            return max(160, min(env_w, sw - 48))
        try:
            mini_max = int(os.environ.get("AIPC_OVERLAY_WIDTH_MINI_MAX", "280"))
            mini_min = int(os.environ.get("AIPC_OVERLAY_WIDTH_MINI_MIN", "132"))
            compact = int(os.environ.get("AIPC_OVERLAY_WIDTH_COMPACT", "280"))
            medium = int(os.environ.get("AIPC_OVERLAY_WIDTH_MEDIUM", "420"))
            wide = int(os.environ.get("AIPC_OVERLAY_WIDTH_WIDE", "0") or "0")
        except ValueError:
            mini_max, mini_min, compact, medium, wide = 280, 132, 280, 420, 0
        if wide <= 0:
            wide = int(max(500, min(620, sw * 0.38)))

        if mini:
            # Dynamic: orb + gap + text + horizontal padding
            tw = self._text_w or self._measure_text_width(text or "執行中")
            # 12+14 pad, 28 orb, 8 gap, +4 fudge
            need = 12 + 28 + 8 + tw + 14 + 4
            return max(mini_min, min(need, mini_max, sw - 48))

        # Measure body lines at the intended type scale
        ty = self._body_typography(body_len, long_form=long_form)
        bf = QFont(self.body._label.font())
        bf.setPixelSize(max(11, int(round(ty["px"]))))
        line_w = 0
        sample = body_text or text or ""
        if sample:
            for ln in sample.replace("\r", "").split("\n")[:8]:
                s = ln.strip()
                if not s:
                    continue
                # Cap single-line measure so one long URL doesn't force ultra-wide
                lw = self._measure_text_width(s[:80], font=bf)
                line_w = max(line_w, lw)
        title_w = self._text_w or self._measure_text_width(text or "", font=self.title.font())
        content_w = max(title_w, line_w)

        # Continuous growth with length + measured content
        # pad ~48 (margins + scrollbar gutter)
        need = content_w + 52
        # Soft floor from char count (CJK-heavy answers need more wrap room)
        soft = int(200 + min(wide - 200, body_len * 1.15))
        if long_form or body_len >= 200:
            target = max(need, soft, compact + 40)
            return max(compact, min(wide, target, sw - 48))
        if body_len >= 72:
            target = max(need, soft, compact)
            return max(compact, min(medium + 40, target, sw - 48))
        # Short answer: hug text, not a fixed 280 box
        target = max(need, 180)
        return max(180, min(target, medium, sw - 48))

    def _clear_root(self) -> None:
        while self._root.count():
            item = self._root.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _apply_layout_mode(self, mode: str) -> None:
        """Rebuild widget tree for mini chip vs full card (no mixed overflow)."""
        if mode == self._layout_mode:
            return
        self._clear_root()
        if mode == "mini":
            if self._chip_row is None:
                self._chip_row = QWidget(self)
                self._chip_row.setStyleSheet("background: transparent;")
                self._chip_layout = QHBoxLayout(self._chip_row)
                self._chip_layout.setContentsMargins(0, 0, 0, 0)
                self._chip_layout.setSpacing(8)
                self._chip_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            assert self._chip_layout is not None
            # re-parent into chip
            self._chip_layout.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignVCenter)
            self._chip_layout.addWidget(self.title, 1, Qt.AlignmentFlag.AlignVCenter)
            self._root.setContentsMargins(12, 8, 14, 8)
            self._root.setSpacing(0)
            self._root.addWidget(self._chip_row, 0, Qt.AlignmentFlag.AlignHCenter)
            self.body.hide()
            self.meta.hide()
        else:
            # full vertical
            if self._chip_layout is not None:
                self._chip_layout.removeWidget(self.orb)
                self._chip_layout.removeWidget(self.title)
            self._root.setContentsMargins(18, 14, 18, 12)
            self._root.setSpacing(6)
            self._root.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignHCenter)
            self._root.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
            self._root.addWidget(self.body)
            self._root.addWidget(self.meta)
            self.title.setMaximumWidth(16777215)
            self.title.setMinimumWidth(0)
        self._layout_mode = mode

    def _set_chrome(self, *, mini: bool) -> None:
        """Shrink chrome for tools-running; restore for answers.

        No-op when mode unchanged — re-applying fonts/margins every tick twitches layout.
        """
        want_orb = 28 if mini else 64
        if mini == self._mini and self.orb.width() == want_orb and self._layout_mode == (
            "mini" if mini else "full"
        ):
            self._mini = mini
            return
        self._mini = mini
        self._apply_layout_mode("mini" if mini else "full")
        if mini:
            self.orb.set_orb_size(28, animate=False)
            f = self.title.font()
            f.setPointSize(11)
            f.setBold(True)
            self.title.setFont(f)
            self.title.setAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            )
            self.title.setWordWrap(False)
            self.title.setStyleSheet(
                "color: #eef2f8; background: transparent; font-weight: 600; "
                "padding: 0; margin: 0;"
            )
            self.body.hide()
            self.meta.hide()
        else:
            self.orb.set_orb_size(64, animate=False)
            f = self.title.font()
            f.setPointSize(12)
            f.setBold(True)
            self.title.setFont(f)
            self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.title.setWordWrap(False)
            self.title.setStyleSheet("color: #f4f6fa; background: transparent;")
            self.meta.setStyleSheet(
                "color: #8b97a8; font-size: 11px; background: transparent; padding-top: 2px;"
            )

    def _set_title_elided(self, text: str, *, max_w: int) -> None:
        """Single-line title that never paints outside the glass card."""
        s = (text or "").strip() or "AIPC"
        self.title.setWordWrap(False)
        w = max(40, int(max_w))
        self.title.setFixedWidth(w)
        fm = QFontMetrics(self.title.font())
        self.title.setText(fm.elidedText(s, Qt.TextElideMode.ElideRight, w))

    def _apply_card_width(
        self,
        *,
        body_len: int = 0,
        long_form: bool = False,
        mini: bool = False,
        text: str = "",
        body_text: str = "",
    ) -> None:
        w = self._desired_card_width(
            body_len=body_len,
            long_form=long_form,
            mini=mini,
            text=text,
            body_text=body_text or str(getattr(self, "_last_shown", "") or text or ""),
        )
        self._card_w = w
        self.setMinimumWidth(w)
        self.setMaximumWidth(w)
        if mini:
            # title gets remaining width after orb + pads
            tw = max(48, w - 12 - 28 - 8 - 14)
            self.title.setFixedWidth(tw)
            if self._chip_row is not None:
                self._chip_row.setFixedWidth(max(80, w - 26))
        else:
            inner = max(100, w - 44)
            self.body.setMinimumWidth(max(80, inner - 8))
            self.body.setMaximumWidth(inner)
            self.meta.setMaximumWidth(inner)
            self.title.setMinimumWidth(0)
            self.title.setMaximumWidth(w - 40)

    def _max_body_height(
        self, *, long_form: bool, body_len: int = 0, mini: bool = False
    ) -> int:
        """Max viewport for body — grows with content up to this, then scroll."""
        if mini:
            return 0  # tools-running: no body block
        _sw, sh = self._screen_metrics()
        try:
            env_h = int(os.environ.get("AIPC_OVERLAY_MAX_BODY_H", "0") or "0")
        except ValueError:
            env_h = 0
        if env_h > 0:
            return max(80, min(env_h, sh - 140))
        # Leave room for orb + title + margins (~140px chrome)
        screen_cap = int(max(200, sh - 160))
        if long_form or body_len >= 200:
            return int(min(screen_cap, max(260, sh * 0.62)))
        if body_len >= 100:
            return int(min(screen_cap, max(180, sh * 0.42)))
        if body_len >= 48:
            return int(min(screen_cap, 200))
        # Short answers: allow full content height (no premature scroll)
        return int(min(screen_cap, 120))

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Mini chip: tighter inset + smaller radius so text isn't chewed by corners
        if self._mini:
            inset = 2.0
            radius = 18.0
        else:
            inset = 5.0
            radius = 22.0
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        # soft drop shadow under card
        shadow = QColor(0, 0, 0, 70)
        for i, off in ((3, 10), (2, 16), (1, 22)):
            sp = QPainterPath()
            sr = rect.adjusted(-i, i + 1, i, i + 3)
            sp.addRoundedRect(sr, radius, radius)
            c = QColor(shadow)
            c.setAlpha(off if not self._mini else max(6, off // 2))
            p.fillPath(sp, c)

        # glass fill
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if self._mini:
            grad.setColorAt(0.0, QColor(18, 22, 32, 242))
            grad.setColorAt(1.0, QColor(12, 16, 24, 248))
        else:
            grad.setColorAt(0.0, QColor(22, 28, 40, 235))
            grad.setColorAt(0.55, QColor(14, 18, 28, 228))
            grad.setColorAt(1.0, QColor(10, 14, 22, 236))
        p.fillPath(path, grad)

        # state accent — top edge full card; mini = left glow bar
        accent = QColor(self._accent)
        if self._mini:
            accent.setAlpha(220)
            pen_a = QPen(accent)
            pen_a.setWidthF(3.0)
            pen_a.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen_a)
            p.drawLine(
                QPoint(int(rect.left() + 3), int(rect.top() + 10)),
                QPoint(int(rect.left() + 3), int(rect.bottom() - 10)),
            )
        else:
            accent.setAlpha(200)
            pen_a = QPen(accent)
            pen_a.setWidthF(2.4)
            p.setPen(pen_a)
            p.drawLine(
                QPoint(int(rect.left() + 28), int(rect.top() + 1)),
                QPoint(int(rect.right() - 28), int(rect.top() + 1)),
            )

        # border
        pen = QPen(QColor(255, 255, 255, 38 if not self._mini else 48))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        if not self._mini:
            # top sheen (full cards only)
            sheen_path = QPainterPath()
            sheen_rect = rect.adjusted(1.5, 1.5, -1.5, -rect.height() * 0.58)
            sheen_path.addRoundedRect(sheen_rect, 20, 20)
            sheen = QLinearGradient(sheen_rect.topLeft(), sheen_rect.bottomLeft())
            sheen.setColorAt(0.0, QColor(255, 255, 255, 28))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillPath(sheen_path, sheen)
        p.end()

    def _stop_opacity_anim(self) -> None:
        if self._opacity_anim is not None:
            try:
                self._opacity_anim.stop()
            except Exception:
                pass
            self._opacity_anim = None

    def _stop_geom_anim(self) -> None:
        if self._geom_anim is not None:
            try:
                self._geom_anim.stop()
            except Exception:
                pass
            self._geom_anim = None
        self._animating_geom = False

    def _fade_to(self, target: float, *, duration: int = 220, on_done=None) -> None:
        self._stop_opacity_anim()
        start = float(self.windowOpacity())
        if abs(start - target) < 0.02:
            self.setWindowOpacity(target)
            if on_done:
                on_done()
            return
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if target > start else QEasingCurve.Type.InCubic
        )
        if on_done:
            anim.finished.connect(on_done)
        self._opacity_anim = anim
        anim.start()

    def _animate_geometry(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        duration: int = 280,
        appear: bool = False,
        on_done=None,
    ) -> None:
        """Smooth size/position tween (mini ↔ expand, appear pop)."""
        end = QRect(x, y, w, h)
        self._stop_geom_anim()
        # Allow intermediate sizes during tween
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)

        if appear or not self.isVisible() or self._last_geom is None:
            # pop from slightly smaller + higher
            sw = max(40, int(w * 0.72))
            sh = max(36, int(h * 0.72))
            sx = x + (w - sw) // 2
            sy = y + max(0, int(h * 0.12))
            start = QRect(sx, sy, sw, sh)
            self.setGeometry(start)
            duration = max(duration, 300)
        else:
            start = self.geometry()
            if (
                abs(start.x() - x) <= 2
                and abs(start.y() - y) <= 2
                and abs(start.width() - w) <= 3
                and abs(start.height() - h) <= 3
            ):
                self.setFixedSize(w, h)
                self.setGeometry(end)
                self._last_geom = (x, y, w, h)
                self._base_y = y
                if on_done:
                    on_done()
                return

        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(end)
        # OutBack overshoot = layout twitch; keep cubic only
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animating_geom = True

        def _finish() -> None:
            self._animating_geom = False
            self.setFixedSize(w, h)
            self.setGeometry(x, y, w, h)
            self._last_geom = (x, y, w, h)
            self._locked_geom = (x, y, w, h)
            self._base_y = y
            self._last_place_t = time.time()
            if on_done:
                on_done()

        anim.finished.connect(_finish)
        self._geom_anim = anim
        anim.start()

    def _show_passive(self, *, force_place: bool = False, animate: bool = True) -> None:
        """Show without activating; fade-in on first appear (no continuous re-layout)."""
        self._fading_out = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        was_hidden = not self.isVisible()
        if was_hidden:
            self.setWindowOpacity(0.0)
            self.show()
            # Appear: snap + fade only (pop-scale fought sizeHint and twitched)
            self._place(force=True, animate=False, appear=False)
            self._raise_top()
            self._fade_to(1.0, duration=200)
            return
        if force_place:
            self._place(force=False, animate=animate)
        self.show()
        self._raise_top()
        if self.windowOpacity() < 0.9:
            self._fade_to(1.0, duration=140)

    def _hide_smooth(self) -> None:
        if self._fading_out or not self.isVisible():
            self.hide()
            self.setWindowOpacity(0.0)
            self._fading_out = False
            return
        self._fading_out = True

        def _after() -> None:
            self.hide()
            self.setWindowOpacity(0.0)
            self._fading_out = False
            self._layout_key = None
            self._locked_geom = None
            self.dismissed.emit()

        self._fade_to(0.0, duration=160, on_done=_after)

    def _on_body_images_changed(self) -> None:
        """After async image load: reflow card height so pics are visible."""
        if self._mini or not self.isVisible():
            return
        try:
            max_view = self._max_body_height(
                long_form=self._long_form, body_len=self._body_len, mini=False
            )
            max_view = max(max_view, min(520, max_view + 220))
            content_h = self.body.measure_content_height(
                max(100, self._card_w - 44)
            )
            view_h = self.body.fit_viewport(max_view, min_h=min(120, content_h or 80))
            self._content_h = content_h
            self._view_h = view_h
            self._locked_geom = None
            self._place(force=True, animate=False)
            self.update()
        except Exception:
            pass

    def _raise_top(self) -> None:
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
        try:
            sc = QGuiApplication.screenAt(QCursor.pos())
            if sc is not None:
                return sc
        except Exception:
            pass
        return QGuiApplication.primaryScreen()

    @staticmethod
    def _anchor_for_state(state: str) -> str:
        """Idle/listening states dock compact to the right; activity/result
        states expand centered. Pure mapping, no env/hardware reads — keep it
        that way so it stays trivially unit-testable."""
        if state in ("listening", "wake", "recording", "no_speech", "followup"):
            return "right"
        return "center"

    def _state_dock_enabled(self) -> bool:
        """AIPC_OVERLAY_ANCHOR (explicit) always wins; otherwise state-driven
        docking is on unless AIPC_OVERLAY_STATE_DOCK=0."""
        if os.environ.get("AIPC_OVERLAY_ANCHOR"):
            return False
        return (os.environ.get("AIPC_OVERLAY_STATE_DOCK", "1") or "1").strip() != "0"

    def _effective_anchor(self, state: str) -> str:
        env_anchor = (os.environ.get("AIPC_OVERLAY_ANCHOR") or "").strip().lower()
        if env_anchor:
            return env_anchor
        if self._state_dock_enabled():
            return self._anchor_for_state(state)
        return "top-center"

    def _mini_for_state(self, state: str) -> bool:
        """Compact pill layout: working/thinking (unchanged) plus any
        state-driven right-docked idle state (reuses the existing narrow
        mini form instead of a bespoke width path)."""
        if state in ("speaking", "done", "error"):
            return False
        if state in ("working", "thinking"):
            return True
        return self._state_dock_enabled() and self._anchor_for_state(state) == "right"

    def _compute_geom(
        self,
        *,
        body_len: int | None = None,
        long_form: bool | None = None,
        mini: bool | None = None,
    ) -> tuple[int, int, int, int] | None:
        screen = self._target_screen()
        if not screen:
            return None
        bl = self._body_len if body_len is None else body_len
        lf = self._long_form if long_form is None else long_form
        is_mini = self._mini if mini is None else mini
        self._apply_card_width(
            body_len=bl,
            long_form=lf,
            mini=is_mini,
            text="",
            body_text=str(getattr(self, "_last_shown", "") or ""),
        )
        avail = screen.availableGeometry()
        full = screen.geometry()
        w = self._card_w
        # Heights from real content chrome + viewport (not a fixed fudge stack)
        if is_mini:
            # Horizontal chip: padding + 28px orb row
            h = 46
        else:
            view = int(getattr(self, "_view_h", 0) or 0)
            meta_h = 22 if self.meta.isVisible() and self.meta.text() else 0
            # margins 14+12, spacing 6×3, orb 64, title ~26
            chrome = 14 + 12 + 6 + 64 + 6 + 26 + 6
            if meta_h:
                chrome += 6 + meta_h
            h = chrome + max(0, view)
            if view <= 0:
                h = max(120, chrome - 6)
            # Short answers: don't leave a huge empty body pocket
            if 0 < view < 48 and bl < 40:
                h = min(h, chrome + view)
        _sw, sh = avail.width(), avail.height()
        max_h = int(min(sh * 0.82, sh - 20))
        h = min(h, max_h)
        margin_y = int(os.environ.get("AIPC_OVERLAY_MARGIN_Y", "14"))
        anchor = self._effective_anchor(self._state)
        if anchor in ("top-right", "right"):
            margin_x = int(os.environ.get("AIPC_OVERLAY_MARGIN_X", "16"))
            x = int(avail.right() - w - margin_x)
        else:
            x = int(avail.left() + (avail.width() - w) / 2)
        y = int(avail.top() + margin_y)
        if y > full.top() + full.height() // 4:
            y = int(full.top() + margin_y)
        return (x, y, w, h)

    def _snap_geom(self, x: int, y: int, w: int, h: int) -> None:
        self._stop_geom_anim()
        self.setFixedSize(w, h)
        self.setGeometry(x, y, w, h)
        self.move(x, y)
        self._last_geom = (x, y, w, h)
        self._locked_geom = (x, y, w, h)
        self._base_y = y
        self._last_place_t = time.time()
        self._pinned_xy = (x, y)

    def _place(
        self,
        *,
        force: bool = False,
        body_len: int | None = None,
        long_form: bool | None = None,
        mini: bool | None = None,
        animate: bool = False,
        appear: bool = False,
    ) -> None:
        if self._animating_geom and not force:
            return
        geom = self._compute_geom(
            body_len=body_len, long_form=long_form, mini=mini
        )
        if geom is None:
            return
        x, y, w, h = geom

        # Frozen: same layout key already on screen — never re-setGeometry
        if (
            not force
            and self._locked_geom is not None
            and self.isVisible()
        ):
            lx, ly, lw, lh = self._locked_geom
            if abs(lw - w) <= 2 and abs(lh - h) <= 2 and abs(lx - x) <= 4:
                return

        size_delta = 0
        x_delta = 0
        if self._last_geom is not None:
            size_delta = abs(self._last_geom[2] - w) + abs(self._last_geom[3] - h)
            x_delta = abs(self._last_geom[0] - x)

        # Animate on real mode transitions (mini↔full size change) OR a
        # right↔center dock slide (x moves a lot without necessarily resizing).
        use_anim = (
            animate
            and self.isVisible()
            and (size_delta >= 40 or x_delta >= 40)
            and not appear
        )
        if use_anim:
            dur = 280 if size_delta > 100 else 200
            self._animate_geometry(x, y, w, h, duration=dur, appear=False)
        else:
            self._snap_geom(x, y, w, h)

    @staticmethod
    def _norm_compact(s: str) -> str:
        return " ".join((s or "").split()).strip()

    @staticmethod
    def _norm_long(s: str) -> str:
        """Keep paragraphs; collapse only trailing spaces / excess blank lines."""
        if not s:
            return ""
        lines = [ln.rstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        out: list[str] = []
        blank = 0
        for ln in lines:
            if not ln.strip():
                blank += 1
                if blank <= 1 and out:
                    out.append("")
                continue
            blank = 0
            out.append(ln)
        return "\n".join(out).strip()

    def _pick_primary(self, state: str, detail: str, partial: str) -> str:
        long_states = ("speaking", "done", "error", "followup")
        if state in long_states:
            d = self._norm_long(detail)
            p = self._norm_long(partial)
        else:
            d = self._norm_compact(detail)
            p = self._norm_compact(partial)
        static = self._norm_compact(STATE_HINTS.get(state, ""))
        if d and static and (d == static or d.startswith(static[:8])):
            d = ""
        if state in ("recording", "followup", "wake"):
            body = p or d
        elif state in ("thinking", "working", "speaking", "done", "error", "no_speech", "miss"):
            body = d or p
        else:
            body = d or p
        if body in ("…", ".", "。"):
            return ""
        return body

    def _pick_meta(self, state: str, primary: str, hint_field: str) -> str:
        static = self._norm_compact(STATE_HINTS.get(state, ""))
        hint_field = self._norm_compact(hint_field)
        cand = static or hint_field
        if not cand:
            return ""
        # Don't duplicate full answer into meta
        if primary and (
            cand == primary
            or (len(cand) > 20 and cand in primary)
            or (len(primary) > 20 and primary in cand)
        ):
            # still allow short static cues for done
            if state == "done" and static and static not in primary:
                return static
            if state != "done":
                return ""
            return static if static and static not in primary else ""
        if primary and state in ("recording", "speaking", "thinking", "working"):
            return ""
        return cand

    def _linkify_urls(self, text: str) -> str:
        """Turn bare https URLs into clickable HTML; highlight multi-media lists."""
        if not text or "<a " in text.lower():
            return text
        import re

        # Escape HTML then restore links
        esc = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        esc = esc.replace("\n", "<br/>")

        def _repl(m: re.Match) -> str:
            url = m.group(0)
            low = url.lower()
            # Image-like: show as blue media chip text (still click-to-open)
            if re.search(r"\.(png|jpe?g|gif|webp|svg)(?:\?|$)", low):
                label = url if len(url) < 64 else (url[:48] + "…")
                return (
                    f'<a href="{url}" style="color:#9ad4ff; text-decoration:none;">'
                    f"🖼 {label}</a>"
                )
            if re.search(r"\.(mp4|webm|m3u8)(?:\?|$)|youtube\.|youtu\.be", low):
                return (
                    f'<a href="{url}" style="color:#ffb4a8; text-decoration:none;">'
                    f"▶ {url if len(url) < 56 else url[:44] + '…'}</a>"
                )
            if ".pdf" in low:
                return (
                    f'<a href="{url}" style="color:#d4c4ff; text-decoration:none;">'
                    f"📄 {url if len(url) < 56 else url[:44] + '…'}</a>"
                )
            return (
                f'<a href="{url}" style="color:#7ec8ff; text-decoration:none;">{url}</a>'
            )

        return re.sub(r"https?://[^\s<>\"']+", _repl, esc)

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
        self._accent = STATE_COLORS.get(state, STATE_COLORS["listening"])

        active = state in SHOW_STATES
        self.orb.set_state(state, active=active and state not in ("error", "done"))

        primary = self._pick_primary(state, detail, partial)
        meta = self._pick_meta(state, primary, hint_field)

        # Tools / thinking: smallest pill. Answers expand height with content.
        # Right-docked idle states (listening/wake/recording/no_speech/followup)
        # reuse the same compact pill so the right-side dock stays narrow.
        is_result = state in ("speaking", "done", "error")
        mini = self._mini_for_state(state)
        # Multi-media answers (any topic) always use long/scroll layout
        url_count = primary.lower().count("http://") + primary.lower().count("https://")
        long_form = is_result and (
            len(primary) > 60
            or "\n" in primary
            or url_count >= 1
            or "相關媒體" in primary
            or "媒体" in primary
        )
        body_len = 0 if mini else len(primary)

        core = _strip_elapsed(primary)
        layout_key = (
            "mini" if mini else ("long" if long_form else "full"),
            state if is_result else ("working" if mini else state),
            core if is_result else core[:48],
            len(primary) if is_result else 0,
        )
        same_layout = layout_key == self._layout_key and self.isVisible()

        # Same mini phase: update label + remeasure width if text length changed
        if same_layout and mini:
            chip = _mini_chip_label(primary or label or "執行中")
            tw = self._measure_text_width(chip)
            # only reflow width if pixel width moved by >6px
            if abs(tw - self._text_w) > 6:
                self._text_w = tw
                self._apply_card_width(
                    body_len=0, long_form=False, mini=True, text=chip
                )
                self._locked_geom = None
                self._place(force=True, animate=False, mini=True)
            else:
                self._text_w = tw
            self._apply_text_contrast(body_len=0)
            self._set_title_elided(chip, max_w=max(48, self._card_w - 28 - 12 - 14 - 8))
            self._last_state = state
            self._hide_at = None
            return

        # Same answer already painted: keep frozen card (no remeasure)
        if same_layout and is_result and primary == self._last_shown:
            self._last_state = state
            return

        prev_mini = self._mini_for_state(self._last_state)
        anchor_switch = self._effective_anchor(self._last_state) != self._effective_anchor(state)
        # Animate on mini↔full switches AND on a right↔center dock move.
        mode_switch = (mini != prev_mini or anchor_switch) and bool(self._last_state)

        self._body_len = body_len
        self._long_form = long_form
        self._set_chrome(mini=mini)
        self._accent = STATE_COLORS.get(state, STATE_COLORS["listening"])
        title = label or STATE_LABELS.get(state) or f"AIPC · {state}"
        if len(title) > 28:
            title = STATE_LABELS.get(state) or "AIPC"

        # Mini: measure text → size chip → contrast → elide only past max
        if mini:
            chip = _mini_chip_label(primary or title)
            self._text_w = self._measure_text_width(chip)
            self._apply_card_width(
                body_len=0, long_form=False, mini=True, text=chip
            )
            self._apply_text_contrast(body_len=0)
            self._set_title_elided(
                chip, max_w=max(48, self._card_w - 28 - 12 - 14 - 8)
            )
            self.body.set_body("", long_form=False, width=0)
            self.body.setFixedHeight(0)
            self.body.hide()
            self.meta.setText("")
            self.meta.hide()
            self._view_h = 0
            self._content_h = 0
            self._last_shown = ""
        else:
            try:
                max_chars = int(os.environ.get("AIPC_OVERLAY_BODY_CHARS", "6000"))
            except ValueError:
                max_chars = 6000
            shown = primary
            if len(shown) > max_chars:
                shown = shown[: max_chars - 1] + "…"

            # Measure title + body BEFORE width so card hugs content
            self._text_w = self._measure_text_width(title)
            self._last_shown = shown or primary  # used by width measure
            ty = self._body_typography(body_len, long_form=long_form)
            self._apply_card_width(
                body_len=body_len,
                long_form=long_form,
                mini=False,
                text=title,
                body_text=shown,
            )
            self._apply_text_contrast(body_len=body_len)
            # Title point size tracks body scale
            tf = self.title.font()
            tf.setPixelSize(13 if body_len >= 200 else (14 if body_len >= 56 else 15))
            tf.setBold(True)
            self.title.setFont(tf)
            self._set_title_elided(title, max_w=max(80, self._card_w - 40))

            if shown:
                max_view = self._max_body_height(
                    long_form=long_form, body_len=body_len, mini=False
                )
                inner_w = max(100, self._card_w - 44)
                fg = getattr(self, "_fg_color", None)
                color = fg.name() if fg is not None else "#eef2f8"
                img_urls = _extract_image_urls(shown)
                if img_urls:
                    # room for rendered images in viewport
                    max_view = max(max_view, min(480, max_view + 200))
                use_html = long_form or (
                    is_result
                    and (
                        "http://" in shown
                        or "https://" in shown
                        or "相關媒體" in shown
                    )
                )
                if use_html:
                    self.body._label.setTextFormat(Qt.TextFormat.RichText)
                    body_src = self._linkify_urls(shown)
                    lf = True
                else:
                    self.body._label.setTextFormat(Qt.TextFormat.PlainText)
                    body_src = shown
                    lf = long_form
                content_h = self.body.set_body(
                    body_src,
                    long_form=lf,
                    width=inner_w,
                    font_px=ty["px"],
                    font_weight=ty["weight"],
                    color=color,
                    line_height=ty["lh"],
                    image_urls=img_urls,
                )
                # Short answers: min viewport tracks content tightly
                if img_urls:
                    min_h = max(100, min(content_h, 160))
                elif body_len < 36:
                    min_h = max(22, min(content_h, 36))
                elif body_len < 80:
                    min_h = 32
                else:
                    min_h = 40
                view_h = self.body.fit_viewport(max_view, min_h=min_h)
                self.body.show()
                self._body_len = body_len
                self._content_h = content_h
                self._view_h = view_h
                self._last_shown = primary
            else:
                self.body.set_body("", long_form=False, width=0, image_urls=[])
                self.body.setFixedHeight(0)
                self.body.hide()
                self._content_h = 0
                self._view_h = 0
                self._last_shown = ""

            if meta and is_result:
                self.meta.setText(meta)
                self.meta.show()
            elif meta and not shown:
                self.meta.setText(meta)
                self.meta.show()
            else:
                self.meta.setText("")
                self.meta.hide()

        # Do NOT adjustSize() — sizeHint jitter is the main layout twitch
        self.update()
        self._layout_key = layout_key
        # Unlock geom so we can place once for this new layout key
        self._locked_geom = None

        self._last_state = state

        if state in SHOW_STATES:
            # Animate on mini ↔ answer mode switch, or a right ↔ center dock move
            self._show_passive(force_place=True, animate=mode_switch)
            if state in ("wake", "recording", "thinking", "working", "speaking", "followup"):
                self._hide_at = None
            elif state == "done":
                try:
                    ttl = float(data.get("ttl_s") or data.get("hold_s") or 0)
                except (TypeError, ValueError):
                    ttl = 0.0
                body = str(data.get("detail") or data.get("partial") or "").strip()
                if ttl <= 0:
                    ttl = 90.0 if len(body) > 200 else (60.0 if len(body) > 12 else 8.0)
                self._hide_at = time.time() + max(8.0, min(ttl, 240.0))
            elif state == "no_speech":
                self._hide_at = time.time() + 1.2
            elif state in ("detecting", "miss"):
                self._hide_at = time.time() + (2.8 if state == "miss" else 2.0)
            else:
                self._hide_at = None
        elif state in HIDE_STATES:
            self._layout_key = None
            self._locked_geom = None
            if state == "listening":
                self._hide_at = time.time() + 0.15
            elif state == "muted":
                self._hide_at = time.time() + 1.2
            else:
                self._hide_at = time.time() + 1.0
        else:
            self._show_passive(force_place=True, animate=False)
            self._hide_at = time.time() + float(data.get("ttl_s") or 10.0)

    def _apply_api_actions(self, actions: list[dict]) -> None:
        for act in actions:
            op = act.get("op")
            if op == "show":
                self._force_hidden = False
                self._show_passive()
                self._hide_at = None
            elif op == "hide":
                self._force_hidden = True
                self._hide_smooth()
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
                    st.get("ttl_s"),
                )

    def _on_poll(self) -> None:
        if self._api is not None:
            acts = self._api.drain_actions()
            if acts:
                self._apply_api_actions(acts)

        if self._force_hidden:
            if self.isVisible() and not self._fading_out:
                self._hide_smooth()
            return

        data = read_status()
        key = (
            data.get("state"),
            data.get("detail"),
            data.get("partial"),
            data.get("label"),
            data.get("hint"),
            data.get("ts"),
            data.get("source"),
            data.get("ttl_s"),
        )
        if getattr(self, "_last_key", None) != key:
            self._last_key = key
            self.apply_status(data)
        if self._hide_at is not None and time.time() >= self._hide_at:
            self._hide_smooth()
            self._hide_at = None
        elif self.isVisible() and not self._fading_out:
            self._raise_top()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    if os.environ.get("AIPC_OVERLAY_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = os.environ["AIPC_OVERLAY_PLATFORM"]
    elif os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
        # XWayland so top-center pin works under KDE Wayland
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    app = QApplication(argv)
    app.setApplicationName("aipc-voice-overlay")
    app.setQuitOnLastWindowClosed(False)

    panel = OverlayPanel()

    def _cleanup() -> None:
        if panel._api is not None:
            panel._api.stop()

    app.aboutToQuit.connect(_cleanup)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
