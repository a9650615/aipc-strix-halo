"""Best-effort mem0 HTTP client for agent-orchestrator.

Phase 2 owns the real memory service. The orchestrator only consumes its
loopback HTTP API and must keep /chat working when mem0 is disabled, missing,
or on a different route shape.
"""

import json
import os
import pwd
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("AIPC_MEM0_ENDPOINT", "http://127.0.0.1:7000").rstrip("/")
TIMEOUT = float(os.environ.get("AIPC_MEM0_TIMEOUT", "1.0"))


def _primary_user() -> str:
    try:
        uids = [int(d) for d in os.listdir("/run/user") if d.isdigit() and int(d) >= 1000]
        if uids:
            return pwd.getpwuid(min(uids)).pw_name
    except (OSError, KeyError, ValueError):
        pass
    return ""


def _user_id(session_id: str) -> str:
    return (
        os.environ.get("AIPC_MEMORY_USER_ID")
        or os.environ.get("AIPC_PRIMARY_USER")
        or _primary_user()
        or os.environ.get("USER")
        or f"session:{session_id}"
    )


def _post(path: str, payload: dict) -> object | None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        ENDPOINT + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read() or b"null")
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError):
        return None


def _format_memories(data: object) -> str:
    if isinstance(data, dict):
        items = data.get("results") or data.get("memories") or data.get("data") or []
    else:
        items = data if isinstance(data, list) else []
    lines = []
    for item in items[:5]:
        if isinstance(item, str):
            lines.append(item)
        elif isinstance(item, dict):
            text = item.get("memory") or item.get("text") or item.get("content")
            if text:
                lines.append(str(text))
    return "\n".join(lines)


def recall(query: str, session_id: str, limit: int = 5) -> str:
    payload = {"query": query, "user_id": _user_id(session_id), "limit": limit}
    # ponytail: mem0 OSS/server route has shifted before; try the two common
    # shapes and keep chat alive if neither exists. Replace once Phase 2 pins it.
    for path in ("/search", "/memories/search"):
        text = _format_memories(_post(path, payload))
        if text:
            return text
    return ""


def remember(text: str, session_id: str) -> None:
    payload = {
        "messages": [{"role": "user", "content": text}],
        "user_id": _user_id(session_id),
        "metadata": {"source": "aipc-agent-orchestrator", "session_id": session_id},
    }
    _post("/memories", payload)


def self_test() -> None:
    global ENDPOINT
    assert _format_memories({"results": [{"memory": "likes concise replies"}]}) == "likes concise replies"
    assert _format_memories([{"text": "uses zh-tw"}]) == "uses zh-tw"
    old_endpoint = ENDPOINT
    ENDPOINT = "http://127.0.0.1:9"
    assert recall("x", "s") == ""
    remember("hello", "s")
    ENDPOINT = old_endpoint
    print("memory self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
