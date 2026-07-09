"""Online backend interface. Real implementation lives in assistant-chatgpt.

v0 skeleton: discover optional module or fail soft with clear errors.
"""

from __future__ import annotations

import importlib
import shutil
from typing import Any, Protocol


class OnlineBackend(Protocol):
    def available(self) -> bool: ...
    def inject_and_send(self, text: str, context_bundle: str = "") -> str: ...
    def turn_voice(self, context_bundle: str = "") -> None: ...
    def session_close(self) -> None: ...
    def voice_stop(self) -> None: ...
    def status(self) -> dict[str, Any]: ...


class NullOnlineBackend:
    def available(self) -> bool:
        return False

    def inject_and_send(self, text: str, context_bundle: str = "") -> str:
        raise RuntimeError(
            "online backend not installed (enable modules/assistant-chatgpt)"
        )

    def turn_voice(self, context_bundle: str = "") -> None:
        raise RuntimeError(
            "online backend not installed (enable modules/assistant-chatgpt)"
        )

    def session_close(self) -> None:
        return None

    def voice_stop(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {"available": False, "reason": "assistant-chatgpt not loaded"}


def _ensure_chatgpt_on_path() -> None:
    import sys
    from pathlib import Path

    # online.py → …/aipc_assistant/backends → parents[6] == modules/
    mod_root = Path(__file__).resolve().parents[6]
    candidates = [
        Path("/usr/lib"),
        mod_root / "assistant-chatgpt" / "files" / "usr" / "lib",
        Path("/var/home/birdyo/aipc-strix-halo/modules/assistant-chatgpt/files/usr/lib"),
    ]
    for c in candidates:
        if (c / "aipc_chatgpt").is_dir() and str(c) not in sys.path:
            sys.path.insert(0, str(c))


def load_online_backend() -> OnlineBackend:
    _ensure_chatgpt_on_path()
    for name in ("aipc_chatgpt", "aipc_chatgpt.backend"):
        try:
            mod = importlib.import_module(name)
            factory = getattr(mod, "get_backend", None)
            if callable(factory):
                be = factory()
                if be is not None and getattr(be, "available", lambda: True)():
                    return be
            if hasattr(mod, "inject_and_send"):
                return mod  # type: ignore[return-value]
        except ImportError:
            continue
        except Exception:
            continue
    if shutil.which("aipc-chatgpt"):
        return CliOnlineBackend()
    # Still try PlaywrightBackend if package importable but available() false later
    try:
        from aipc_chatgpt.backend import PlaywrightBackend

        be = PlaywrightBackend()
        if be.available():
            return be
    except ImportError:
        pass
    return NullOnlineBackend()


class CliOnlineBackend:
    """Invoke aipc-chatgpt CLI if present (assistant-chatgpt module)."""

    def available(self) -> bool:
        return bool(shutil.which("aipc-chatgpt"))

    def inject_and_send(self, text: str, context_bundle: str = "") -> str:
        import subprocess

        payload = (context_bundle + "\n\n" + text).strip() if context_bundle else text
        r = subprocess.run(
            ["aipc-chatgpt", "inject", "--send", payload],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "inject failed")
        return (r.stdout or "").strip()

    def turn_voice(self, context_bundle: str = "") -> None:
        import subprocess

        cmd = ["aipc-chatgpt", "turn", "--voice"]
        if context_bundle:
            cmd.extend(["--context", context_bundle])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        if r.returncode != 0:
            raise RuntimeError(
                r.stderr.strip() or r.stdout.strip() or "turn --voice failed"
            )

    def session_close(self) -> None:
        import subprocess

        subprocess.run(
            ["aipc-chatgpt", "session", "close"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def voice_stop(self) -> None:
        import subprocess

        subprocess.run(
            ["aipc-chatgpt", "voice", "stop"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def status(self) -> dict[str, Any]:
        return {"available": self.available(), "via": "aipc-chatgpt CLI"}
