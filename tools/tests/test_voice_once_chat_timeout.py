"""aipc-voice-once chat(): urllib timeout must become spoken 处理超时, not exit 1."""
from __future__ import annotations

import importlib.util
import socket
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
VOICE_ONCE = ROOT / "modules/voice-pipecat/files/usr/bin/aipc-voice-once"


def _load_once():
    """Load shipped bin (no .py suffix) via SourceFileLoader."""
    assert VOICE_ONCE.is_file()
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader

    loader = SourceFileLoader("aipc_voice_once_under_test", str(VOICE_ONCE))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def once():
    return _load_once()


def test_is_timeout_exc_recognizes_urlerror_timeouterror(once):
    assert once._is_timeout_exc(TimeoutError("timed out")) is True
    assert once._is_timeout_exc(urllib.error.URLError(TimeoutError("timed out"))) is True
    assert once._is_timeout_exc(urllib.error.URLError(socket.timeout("timed out"))) is True
    assert once._is_timeout_exc(urllib.error.URLError(ConnectionRefusedError("refused"))) is False
    assert once._is_timeout_exc(OSError("connection timed out")) is True


def test_chat_urlerror_timeout_returns_chinese_timeout_text(once):
    """Real urlopen path raises URLError(reason=TimeoutError), not bare TimeoutError."""

    def boom(*_a, **_k):
        raise urllib.error.URLError(TimeoutError("The read operation timed out"))

    with patch.object(once.urllib.request, "urlopen", side_effect=boom):
        text = once.chat("hello", "s-timeout")
    assert "处理超时" in text
    assert str(int(once.CHAT_TIMEOUT)) in text or f"{once.CHAT_TIMEOUT:.0f}" in text


def test_chat_bare_timeout_error_also_spoken(once):
    with patch.object(
        once.urllib.request, "urlopen", side_effect=TimeoutError("timed out")
    ):
        text = once.chat("hello", "s-bare")
    assert "处理超时" in text


def test_chat_connection_refused_still_raises(once):
    def boom(*_a, **_k):
        raise urllib.error.URLError(ConnectionRefusedError("Connection refused"))

    with patch.object(once.urllib.request, "urlopen", side_effect=boom):
        with pytest.raises(urllib.error.URLError):
            once.chat("hello", "s-refused")
