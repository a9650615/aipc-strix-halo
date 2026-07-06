"""Screenshot -> LiteLLM vision model bridge (phase-4-agent#4.8).

Capture: `spectacle -b -n -o <file>` (KDE's own CLI, Wayland-native;
`-b` = background/no GUI, `-n` = no notification) — hardware-verified on
this box: produced a real 2560x1600 PNG in ~1s.

Model: design.md D2/D6 name the vision alias `vlm-qwen2vl`. Checked
`GET http://127.0.0.1:4000/v1/models` on this machine directly: it is NOT
in the list (resident-small, coder-agentic, ornith-35b, main-cloud,
coder-cloud, thinking-cloud, gpt4o-cloud, gemini-cloud only). Reading
`modules/llm-models/files/etc/aipc/models/models.yaml`: `vlm-qwen2vl` was
one of the aliases explicitly cut in the 2026-07-04 trim ("too many
resident/on-demand models loaded for no real benefit"). Confirmed live:
POSTing `{"model": "vlm-qwen2vl", ...}` to `/v1/chat/completions` returns
HTTP 400 "Invalid model name passed in model=vlm-qwen2vl".
NO vision-capable model is currently registered in LiteLLM at all —
`gpt4o-cloud`/`gemini-cloud` are vision-capable upstream but are cloud
aliases gated on secrets (CLAUDE.md §5); whether their keys are actually
decrypted on this box was not checked here and is a separate question.
This is a real gap, not a naming mismatch — flagging for the 大哥 rather
than silently swapping the constant below to a cloud alias, per this
dispatch's brief. VLM_MODEL stays `vlm-qwen2vl`, matching the spec; every
call against it will 400 until either the alias is restored or the 大哥
picks a replacement.
"""

import base64
import json
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from aipc_agent_screen_control import gate

LITELLM_BASE_URL = "http://127.0.0.1:4000"
VLM_MODEL = "vlm-qwen2vl"  # see module docstring — not currently registered
DEFAULT_PROMPT = "Describe the visible UI layout: windows, buttons, text fields, and their approximate positions."


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


def describe_screen(prompt: str = DEFAULT_PROMPT, model: str = VLM_MODEL) -> dict:
    """Screenshot -> base64 -> LiteLLM vision chat completion -> parsed
    text description. Calls gate.check_action() first (screen-control
    grant + blacklist), same as every input.py action."""
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
    }).encode()

    req = urllib.request.Request(
        f"{LITELLM_BASE_URL}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            reply = json.load(resp)
    except urllib.error.HTTPError as exc:
        # matches this repo's structured "not_configured"/status-dict tool
        # convention (see agent-orchestrator/daily_assistant.py) rather than
        # raising — expected outcome right now since VLM_MODEL isn't
        # registered (see module docstring).
        return {"status": "error", "detail": exc.read().decode(errors="replace")}
    return {
        "status": "ok",
        "description": reply["choices"][0]["message"]["content"],
    }


def self_test() -> None:
    """ponytail: proves the fail-closed gate path only (no gate socket on
    this host -> GateDenied before any screenshot is even taken). Real
    screenshot capture and the VLM call itself were exercised manually
    during this dispatch (see README), not re-run here — self_test must
    stay fast/offline for verify.sh, it shouldn't shell out to spectacle
    or hit the network on every render check."""
    try:
        describe_screen()
        raise AssertionError("describe_screen did not fail closed with no gate")
    except gate.GateDenied:
        pass
    print("self-test passed (fail-closed with no gate socket present)")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
