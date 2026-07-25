"""Tray shell compatibility layer (sni_menu vs window)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parents[1] / "files" / "usr" / "lib" / "codexbar-gui"
sys.path.insert(0, str(GUI_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_choose_shell_mode_override() -> None:
    from codexbar_gui.shell_adapter import choose_shell_mode

    os.environ["CODEXBAR_TRAY_SHELL"] = "window"
    assert choose_shell_mode() == "window"
    os.environ["CODEXBAR_TRAY_SHELL"] = "sni_menu"
    assert choose_shell_mode() == "sni_menu"
    del os.environ["CODEXBAR_TRAY_SHELL"]
    # Default is window (reliable open)
    assert choose_shell_mode() == "window"


def test_embedded_popover_constructs() -> None:
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.popover import UsagePopover

    _ = QApplication.instance() or QApplication([])
    pop = UsagePopover(embedded=True, web_url="http://127.0.0.1:8787/")
    assert pop._embedded is True
    assert pop._web_btn.isEnabled()
    closer = {"n": 0}

    def _c() -> None:
        closer["n"] += 1

    pop.set_host_closer(_c)
    pop.close_host()
    assert closer["n"] == 1


def test_build_sni_menu_shell() -> None:
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from codexbar_gui.popover import UsagePopover
    from codexbar_gui.shell_adapter import build_tray_shell

    _ = QApplication.instance() or QApplication([])
    tray = QSystemTrayIcon()
    pop = UsagePopover(embedded=False)
    shell = build_tray_shell(tray, pop, mode="sni_menu")
    assert shell.mode == "sni_menu"
    shell.attach()
    assert tray.contextMenu() is not None
    shell.on_views([])
    shell.close()


def test_reliable_click_pos_rejects_origin() -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from codexbar_gui.shell_adapter import reliable_click_pos

    _ = QApplication.instance() or QApplication([])
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    avail = screen.availableGeometry()
    pos = reliable_click_pos(QPoint(0, 0), tray=None)
    # Must not stay at desktop origin — dock near top-right of a screen
    assert not (pos.x() <= 2 and pos.y() <= 2)
    assert pos.y() <= avail.top() + 40 or pos.x() >= avail.right() - 40