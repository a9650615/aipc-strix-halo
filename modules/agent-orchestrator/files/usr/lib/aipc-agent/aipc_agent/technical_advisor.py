"""Bounded local technical advice for Hermes."""

from __future__ import annotations

import json
import os
import re
import urllib.request

from aipc_agent._util import text_of

MODEL = os.environ.get("AIPC_TECH_ADVISOR_MODEL", "ornith-35b")
BASE_URL = os.environ.get("AIPC_LITELLM_URL", "http://127.0.0.1:4000").rstrip("/")
TIMEOUT = float(os.environ.get("AIPC_TECH_ADVISOR_TIMEOUT", "45"))
_CODE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_TECHNICAL = re.compile(r"traceback|exception|error|warning|failed|stack|version|python|node|linux|systemd|http|curl|npm|pip|docker|podman|git|ya?ml|json|toml|\w+\s*=", re.I)
_SECRET = re.compile(r"(?i)(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+|\bsk-[A-Za-z0-9_-]{12,}\b")
_REFUSAL = re.compile(r"cannot[_ ]assist|can(?:not|'t) help|unable to help|不能協助|无法协助", re.I)


def build_packet(text: str) -> str:
    code = _CODE.findall(text or "")
    lines = [line.strip() for line in (text or "").splitlines() if _TECHNICAL.search(line)]
    artifacts = "\n".join([*code, *lines])[:6000]
    artifacts = _SECRET.sub("[redacted]", artifacts).strip()
    if not artifacts:
        return ""
    return (
        "Solve this technical subtask without inferring or discussing the user scenario. "
        "Return only diagnosis, implementation options, and validation steps.\n\n"
        f"TECHNICAL ARTIFACTS:\n{artifacts}"
    )


def _chat(packet: str) -> str:
    base = BASE_URL if BASE_URL.endswith("/v1") else BASE_URL + "/v1"
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a local technical advisor."},
            {"role": "user", "content": packet},
        ],
        "max_tokens": 600,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer aipc-local"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        data = json.loads(response.read().decode())
    return text_of((data.get("choices") or [{}])[0].get("message", {}).get("content")).strip()


def advise(text: str) -> str | None:
    packet = build_packet(text)
    if not packet:
        return None
    try:
        answer = _chat(packet)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-agent: technical advisor unavailable: {exc}", flush=True)
        return None
    return None if not answer or _REFUSAL.search(answer) else answer[:4000]
