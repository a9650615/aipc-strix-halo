from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _persona_name() -> str:
    for p in (
        Path("/etc/aipc/voice/persona.yaml"),
        Path(__file__).resolve().parents[4]
        / "voice-pipecat"
        / "files"
        / "etc"
        / "aipc"
        / "voice"
        / "persona.yaml",
    ):
        if not p.is_file():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("name:"):
                    return line.split(":", 1)[1].strip().strip("\"'")
        except OSError:
            continue
    return ""


def _mem0_facts(query: str, top_k: int = 5) -> list[str]:
    # Soft-fail: mem0 HTTP shape varies; never block a turn.
    url = "http://127.0.0.1:8080/search"  # common local; may not exist
    try:
        body = json.dumps({"query": query, "limit": top_k}).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            data = json.loads(resp.read().decode())
        if isinstance(data, list):
            return [str(x.get("memory") or x.get("text") or x)[:200] for x in data[:top_k]]
        if isinstance(data, dict) and "results" in data:
            return [str(r)[:200] for r in data["results"][:top_k]]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, TypeError):
        pass
    return []


def assemble_bundle(user_text: str = "", include_mem0: bool = True) -> str:
    parts = ["[aipc context — auto inject]"]
    now = datetime.now(timezone.utc).astimezone()
    parts.append(f"time: {now.isoformat(timespec='seconds')}")
    name = _persona_name()
    if name:
        parts.append(f"assistant_persona: {name}")
    if include_mem0:
        facts = _mem0_facts(user_text or "preferences")
        if facts:
            parts.append("mem0:")
            parts.extend(f"- {f}" for f in facts)
    parts.append(
        "note: You are the online assistant path of an aipc AI PC; "
        "local tools may be unavailable unless described in context."
    )
    return "\n".join(parts)
