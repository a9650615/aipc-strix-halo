"""Tests for desktop-see routing and keyword matching."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "modules/agent-orchestrator/files/usr/lib/aipc-agent"
sys.path.insert(0, str(AGENT))


def _load_screen_see():
    path = AGENT / "aipc_agent/screen_see.py"
    spec = importlib.util.spec_from_file_location("screen_see_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_wants_screen_see_keywords():
    m = _load_screen_see()
    assert m.wants_screen_see("看一下桌面")
    assert m.wants_screen_see("螢幕上有什么")
    assert m.wants_screen_see("what's on screen")
    assert m.wants_screen_see("describe the desktop")
    assert not m.wants_screen_see("今天天气怎么样")
    assert not m.wants_screen_see("打开浏览器")


def test_screen_see_self_test():
    m = _load_screen_see()
    m.self_test()
