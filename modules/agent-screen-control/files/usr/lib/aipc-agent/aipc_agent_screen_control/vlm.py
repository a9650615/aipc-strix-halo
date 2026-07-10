"""Screenshot -> LiteLLM vision model bridge (phase-4-agent#4.8).

Capture: `spectacle -b -n -o <file>` (KDE's own CLI, Wayland-native;
`-b` = background/no GUI, `-n` = no notification) — hardware-verified on
this box: produced a real 2560x1600 PNG in ~1s.

Default LiteLLM model is `vlm-screen` (Qwen2.5-VL-7B for UI/OCR).
`vlm-qwen2vl` remains the uncensored Gemma4+mmproj stack. Assistant
desktop-look uses aipc_agent.screen_see (no gate); this module defaults
to require_gate for computer-use style callers.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from aipc_agent_screen_control import gate

LITELLM_BASE_URL = os.environ.get("AIPC_LITELLM_URL", "http://127.0.0.1:4000").rstrip("/")
# Prefer screen UI/OCR model; uncensored gemma vision remains vlm-qwen2vl.
VLM_MODEL = os.environ.get("AIPC_SCREEN_VLM", "vlm-screen")
DEFAULT_PROMPT = (
    "Describe the visible UI layout: windows, buttons, text fields, "
    "and their approximate positions. Be concise."
)
VLM_TIMEOUT = float(os.environ.get("AIPC_SCREEN_VLM_TIMEOUT", "180"))


def capture_screenshot() -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        subprocess.run(
            ["spectacle", "-b", "-n", "-o", str(tmp_path)],
            check=True, capture_output=True, timeout=10,
        )
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def describe_screen(
    prompt: str = DEFAULT_PROMPT,
    model: str = VLM_MODEL,
    *,
    require_gate: bool = True,
) -> dict:
    """Screenshot -> base64 -> LiteLLM vision chat completion.

    require_gate=True (default for screen-control module consumers): gate +
    blacklist first. Assistant desktop-look uses aipc_agent.screen_see instead
    (read-only, no gate).
    """
    if require_gate:
        gate.check_action()
    png_bytes = capture_screenshot()
    b64 = base64.b64encode(png_bytes).decode()

    body = json.dumps({
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        "max_tokens": 384,
    }).encode()

    req = urllib.request.Request(
        f"{LITELLM_BASE_URL}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=VLM_TIMEOUT) as resp:
            reply = json.load(resp)
    except urllib.error.HTTPError as exc:
        return {"status": "error", "detail": exc.read().decode(errors="replace")}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}
    msg = reply["choices"][0]["message"]
    text = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    return {
        "status": "ok",
        "description": text,
        "model": model,
    }


def self_test() -> None:
    """Fail-closed gate path only when require_gate=True (default)."""
    try:
        describe_screen(require_gate=True)
        raise AssertionError("describe_screen did not fail closed with no gate")
    except gate.GateDenied:
        pass
    print("self-test passed (fail-closed with no gate socket present)")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
