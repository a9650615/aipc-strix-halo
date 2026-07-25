"""Absolute window placement on KDE Wayland.

KWin drops client-set positions for ``xdg_toplevel`` surfaces: ``move()`` /
``QWindow.setPosition`` are silently ignored (Qt keeps reporting the requested
rect while the window actually sits wherever KWin placed it — usually screen
centre). The supported way to dock a tray popover is to ask KWin itself: load a
KWin script over D-Bus and let it set ``frameGeometry``.

The script is **armed before the popover is shown** and stays resident for a
moment, docking the window from ``workspace.windowAdded``. Two reasons:

- placing after the map is visible as a jump from screen centre;
- a geometry change after KWin granted activation *drops* that activation, and
  Wayland has no ``activateWindow()`` to win it back.

Everything is computed inside KWin because the client cannot see the truth:

- ``workspace.clientArea(PlacementArea, output, …)`` is the only panel-aware work
  area under Wayland (Qt's ``availableGeometry()`` equals the full screen, and
  ``_NET_WORKAREA`` is XWayland-only, device-pixel scaled and unioned across
  outputs);
- the **output** comes from the tray icon, so a multi-monitor setup docks on the
  screen that owns the panel, not on the primary one;
- when Plasma refuses to report a tray rect (``anchor_real=False``), KWin looks up
  the panel (``dock``) window on the active output and derives the anchor from its
  geometry and edge.

Dismissal is asked of KWin too (:func:`poll_dismiss`), for the same reason: only
the compositor knows the real cursor position and which window is truly active.
"""

from __future__ import annotations

import itertools
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("codexbar_gui.kwin_place")

WINDOW_TITLE = "CodexBar Usage Popover"

# How far outside the card/tray-icon box the cursor still counts as "engaged".
CURSOR_PAD = 32
# A card the cursor never came near closes after this long even if it keeps focus.
UNTOUCHED_CAP_S = 12.0
# CODEXBAR_KWIN_DEBUG=1 makes the poll report its inputs over D-Bus (KWin's own
# print() does not reach the journal on this system):
#   busctl --user monitor --match "interface='io.aipc.CodexbarProbe'"
DEBUG = os.environ.get("CODEXBAR_KWIN_DEBUG", "").strip() in {"1", "true", "yes"}

_seq = itertools.count(1)
_armed: Optional[str] = None

_JS_TEMPLATE = """
var anchor = {x: %(ax)d, y: %(ay)d, w: %(aw)d, h: %(ah)d};
var anchorReal = %(real)d;
var want = {w: %(w)d, h: %(h)d};
var title = "%(title)s";

function outputs() {
    if (typeof workspace.screens !== "undefined") { return workspace.screens; }
    return [];
}

function activeOutput(fallback) {
    if (typeof workspace.activeScreen !== "undefined" && workspace.activeScreen) {
        return workspace.activeScreen;
    }
    if (typeof workspace.activeOutput !== "undefined" && workspace.activeOutput) {
        return workspace.activeOutput;
    }
    return fallback;
}

function outputAt(pt, fallback) {
    if (typeof workspace.screenAt === "function") {
        var out = workspace.screenAt(pt);
        if (out) { return out; }
    }
    return fallback;
}

function panelOn(out) {
    var best = null;
    var wins = workspace.windowList();
    for (var i = 0; i < wins.length; i++) {
        var c = wins[i];
        if (!c.dock) { continue; }
        if (out && c.output && c.output !== out) { continue; }
        if (best === null || c.width * c.height > best.width * best.height) { best = c; }
    }
    return best;
}

/* Tray icons live at the far end of the panel: right for a horizontal panel,
   bottom for a vertical one. */
function anchorFromPanel(panel) {
    var g = panel.frameGeometry;
    if (g.width >= g.height) {
        return {x: g.x + g.width - 28, y: g.y, w: 24, h: g.height};
    }
    return {x: g.x, y: g.y + g.height - 28, w: g.width, h: 24};
}

function place(c) {
    var out = c.output;
    if (anchorReal) {
        out = outputAt({x: anchor.x + anchor.w / 2, y: anchor.y + anchor.h / 2}, out);
    } else {
        out = activeOutput(out);
        var panel = panelOn(out);
        if (panel) { anchor = anchorFromPanel(panel); }
    }
    var area = workspace.clientArea(KWin.PlacementArea, out, workspace.currentDesktop);
    var h = Math.min(want.h, area.height - 8);
    var w = Math.min(want.w, area.width - 8);
    var y;
    if (anchor.y + anchor.h / 2 < area.y + area.height / 2) {
        y = Math.max(area.y + 4, anchor.y + anchor.h + 4);
    } else {
        y = Math.min(anchor.y - h - 4, area.y + area.height - h - 4);
    }
    y = Math.max(area.y + 4, Math.min(y, area.y + area.height - h - 4));
    var x = anchor.x + anchor.w / 2 - w / 2;
    x = Math.max(area.x + 4, Math.min(x, area.x + area.width - w - 4));
    c.frameGeometry = {x: Math.round(x), y: Math.round(y), width: w, height: h};
    print("codexbar-place: docked at " + c.frameGeometry.x + "," + c.frameGeometry.y);
}

function mine(c) {
    return c && c.caption && c.caption.indexOf(title) >= 0;
}

var existing = workspace.windowList();
for (var i = 0; i < existing.length; i++) {
    if (mine(existing[i])) { place(existing[i]); }
}
workspace.windowAdded.connect(function (c) {
    if (mine(c)) { place(c); }
});
"""


def build_script(
    anchor,
    width: int,
    height: int,
    *,
    anchor_real: bool = True,
    title: str = WINDOW_TITLE,
) -> str:
    """Render the KWin placement script (pure — the unit-testable half)."""
    return _JS_TEMPLATE % {
        "ax": int(anchor.x()),
        "ay": int(anchor.y()),
        "aw": max(1, int(anchor.width())),
        "ah": max(1, int(anchor.height())),
        "real": 1 if anchor_real else 0,
        "w": int(width),
        "h": int(height),
        "title": title,
        "pad": CURSOR_PAD,
    }


# Polled dismissal. A Wayland client cannot see the cursor outside its own
# surface, nor which window is really active, so it can never tell "user clicked
# elsewhere" from "a background app grabbed focus while the user reads" — and a
# click on an *already focused* window raises no activation signal at all. KWin
# knows all three, so it decides and closes the card itself.
_POLL_JS_TEMPLATE = """
var anchor = {x: %(ax)d, y: %(ay)d, w: %(aw)d, h: %(ah)d};
var title = "%(title)s";
var pad = %(pad)d;
var openMs = %(open_ms)d;
var capMs = %(cap_ms)d;

function mine(c) {
    return c && c.caption && c.caption.indexOf(title) >= 0;
}

function popover() {
    var wins = workspace.windowList();
    for (var i = 0; i < wins.length; i++) {
        if (mine(wins[i])) { return wins[i]; }
    }
    return null;
}

/* Cursor on the card, on the tray icon, or in the gap between them. */
function cursorEngaged(pop) {
    var p = workspace.cursorPos;
    var g = pop.frameGeometry;
    var left = Math.min(g.x, anchor.x) - pad;
    var right = Math.max(g.x + g.width, anchor.x + anchor.w) + pad;
    var top = Math.min(g.y, anchor.y) - pad;
    var bottom = Math.max(g.y + g.height, anchor.y + anchor.h) + pad;
    return p.x >= left && p.x <= right && p.y >= top && p.y <= bottom;
}

var pop = popover();
if (pop !== null) {
    var act = workspace.activeWindow;
    var engaged = cursorEngaged(pop);
    var oursActive = mine(act);
    if (%(debug)d) {
        var c = workspace.cursorPos;
        var g = pop.frameGeometry;
        callDBus("io.aipc.CodexbarProbe", "/", "io.aipc.CodexbarProbe", "report",
            "poll cursor=" + c.x + "," + c.y +
            " card=" + g.x + "," + g.y + " " + g.width + "x" + g.height +
            " anchor=" + anchor.x + "," + anchor.y + " " + anchor.w + "x" + anchor.h +
            " engaged=" + engaged + " oursActive=" + oursActive +
            " active=" + (act ? act.caption : "null") +
            " openMs=" + openMs + "/" + capMs);
    }
    /* The cursor being on the card (or its tray icon) always means "user is here".
       Otherwise: another window holding focus means they moved on, and the cap
       stops a card nobody touched from living forever when focus never changes. */
    if (!engaged) {
        if (!oursActive) {
            print("codexbar-place: closing, cursor and focus are elsewhere");
            pop.closeWindow();
        } else if (openMs >= capMs) {
            print("codexbar-place: closing, untouched for " + openMs + "ms");
            pop.closeWindow();
        }
    }
}
"""


def build_poll_script(
    anchor,
    *,
    open_seconds: float = 0.0,
    cap_seconds: float = UNTOUCHED_CAP_S,
    title: str = WINDOW_TITLE,
) -> str:
    """Render the polled dismissal script (pure — the unit-testable half)."""
    return _POLL_JS_TEMPLATE % {
        "ax": int(anchor.x()),
        "ay": int(anchor.y()),
        "aw": max(1, int(anchor.width())),
        "ah": max(1, int(anchor.height())),
        "title": title,
        "pad": CURSOR_PAD,
        "open_ms": int(max(0.0, open_seconds) * 1000),
        "cap_ms": int(cap_seconds * 1000),
        "debug": 1 if DEBUG else 0,
    }


def _script_path() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return Path(base) / f"codexbar-place-{os.getpid()}.js"


def _scripting():
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
    except ImportError:
        return None
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    iface = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", bus)
    return iface if iface.isValid() else None


def arm(
    anchor,
    width: int,
    height: int,
    *,
    anchor_real: bool = True,
    title: str = WINDOW_TITLE,
) -> bool:
    """Dock the popover next to ``anchor`` now and when KWin maps it.

    ``anchor`` is a QRect in Qt global (logical) coords — the tray icon rect.
    Pass ``anchor_real=False`` when it is a guess, so KWin derives one from the
    panel on the active output instead. Call before ``show()``; release with
    :func:`disarm`.
    """
    global _armed
    disarm()
    scripting = _scripting()
    if scripting is None:
        return False

    path = _script_path()
    try:
        path.write_text(
            build_script(anchor, width, height, anchor_real=anchor_real, title=title)
        )
    except OSError:
        logger.warning("cannot write KWin placement script to %s", path)
        return False

    name = f"codexbar-place-{os.getpid()}-{next(_seq)}"
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface

        reply = scripting.call("loadScript", str(path), name)
        args = reply.arguments()
        sid = int(args[0]) if args else -1
        if sid < 0:
            return False
        runner = QDBusInterface(
            "org.kde.KWin",
            f"/Scripting/Script{sid}",
            "org.kde.kwin.Script",
            QDBusConnection.sessionBus(),
        )
        if not runner.isValid():
            scripting.call("unloadScript", name)
            return False
        runner.call("run")
        _armed = name
        return True
    except Exception:
        logger.warning("KWin placement failed", exc_info=True)
        return False


def _run_once(js: str, tag: str) -> bool:
    """Load, run and unload a throwaway KWin script."""
    scripting = _scripting()
    if scripting is None:
        return False
    path = Path(
        os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    ) / f"codexbar-{tag}-{os.getpid()}.js"
    try:
        path.write_text(js)
    except OSError:
        return False
    name = f"codexbar-{tag}-{os.getpid()}-{next(_seq)}"
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface

        reply = scripting.call("loadScript", str(path), name)
        args = reply.arguments()
        sid = int(args[0]) if args else -1
        if sid < 0:
            return False
        runner = QDBusInterface(
            "org.kde.KWin",
            f"/Scripting/Script{sid}",
            "org.kde.kwin.Script",
            QDBusConnection.sessionBus(),
        )
        if not runner.isValid():
            return False
        runner.call("run")
        return True
    except Exception:
        logger.debug("KWin %s script failed", tag, exc_info=True)
        return False
    finally:
        try:
            scripting.call("unloadScript", name)
        except Exception:
            pass


def poll_dismiss(
    anchor,
    *,
    open_seconds: float = 0.0,
    title: str = WINDOW_TITLE,
) -> bool:
    """Let KWin close the card if the cursor *and* focus have both moved on."""
    return _run_once(
        build_poll_script(anchor, open_seconds=open_seconds, title=title), "dismiss"
    )


def disarm() -> None:
    """Unload the resident placement script (no-op when nothing is armed)."""
    global _armed
    if _armed is None:
        return
    name, _armed = _armed, None
    scripting = _scripting()
    if scripting is None:
        return
    try:
        scripting.call("unloadScript", name)
    except Exception:
        logger.debug("unloadScript %s failed", name, exc_info=True)
