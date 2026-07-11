"""Pure-helper tests for the overlay markdown + media layer (headless).

openspec/design: 2026-07-11 overlay markdown + image/text layout.
Qt is used offscreen; skips cleanly if PySide6 is not installed.
"""

from __future__ import annotations

import importlib.util
import os
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OVL = REPO / "modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_overlay.py"


def _load():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    loader = SourceFileLoader("aipc_voice_overlay", str(OVL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _mod():
    pytest.importorskip("PySide6")
    return _load()


def test_extract_and_strip_markdown_image():
    m = _mod()
    clean, urls = m._extract_and_strip_media("see ![cat](https://x.test/c.png) here")
    assert urls == ["https://x.test/c.png"]
    assert "https://x.test/c.png" not in clean
    assert "see" in clean and "here" in clean


def test_extract_merges_explicit_and_dedupes():
    m = _mod()
    clean, urls = m._extract_and_strip_media(
        "a https://x.test/p.jpg b", extra=["https://x.test/p.jpg"]
    )
    assert urls == ["https://x.test/p.jpg"]
    assert "https://x.test/p.jpg" not in clean


def test_non_image_link_stays_in_text():
    m = _mod()
    clean, urls = m._extract_and_strip_media("read https://x.test/article here")
    assert urls == []
    assert "https://x.test/article" in clean


def test_markdown_bold_and_list_render_html():
    m = _mod()
    html = m._markdown_to_html("**hi**\n\n- one\n- two")
    assert "<" in html
    low = html.lower()
    assert ("font-weight" in low) or ("<b" in low) or ("<strong" in low)
    assert "one" in html and "two" in html


def test_markdown_empty_is_empty():
    m = _mod()
    assert m._markdown_to_html("   ") == ""


def test_source_host():
    m = _mod()
    assert m._source_host("https://www.cwa.gov.tw/V8/C/x.png") == "cwa.gov.tw"
    assert m._source_host("not a url") == ""


def test_set_body_renders_markdown_widget():
    m = _mod()
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    body = m.BodyScroll()
    # no image URL → no network fetch
    body.set_body("**strong** and text", long_form=False, width=280)
    html = body.body_text()
    assert "strong" in html
    assert ("font-weight:700" in html) or ("<b" in html.lower())
