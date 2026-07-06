"""Search tools for agent sub-agents (phase-4-agent#1.7, 4.5, 4.6).

SearXNG is the default, self-hosted backend -- the quadlet in this module
binds it to loopback (`env/endpoint`). Tavily is an opt-in paid upgrade,
advertised only when TAVILY_API_KEY is available -- never baked in
(CLAUDE.md §5). Both fail soft: an unreachable/misconfigured backend
returns a status dict, never an exception, so a sub-agent's tool call
degrades instead of crashing the graph (same discipline as
aipc_agent/memory.py).
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

SEARXNG_ENDPOINT = os.environ.get("AIPC_SEARXNG_ENDPOINT", "http://127.0.0.1:8888").rstrip("/")
TAVILY_ENDPOINT = "https://api.tavily.com/search"
TIMEOUT = float(os.environ.get("AIPC_SEARCH_TIMEOUT", "5.0"))

# ponytail: cloud-llm-fallback's decrypt-cloud-keys.sh (modules/secrets-sops,
# out of this module's scope) only extracts anthropic/openai/gemini keys
# today -- TAVILY_API_KEY isn't in its awk script yet, so this file won't
# actually contain it until that script is updated. Reading it here is the
# documented target location; os.environ is checked first in case a future
# systemd EnvironmentFile= wires it in directly.
TAVILY_ENV_FILE = os.environ.get(
    "AIPC_TAVILY_ENV_FILE", "/etc/aipc/env.d/llm-litellm/cloud-keys.env"
)


def _request_json(req: urllib.request.Request) -> object | None:
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError, ValueError):
        return None


def _normalize(raw_results: list, limit: int) -> list[dict]:
    results = []
    for item in raw_results[:limit]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
            }
        )
    return results


def search_searxng(query: str, limit: int = 5) -> dict:
    """Query the loopback SearXNG instance (`SEARXNG_ENDPOINT`) and return
    a structured result. Fails soft (status: error) if unreachable."""
    url = SEARXNG_ENDPOINT + "/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json"}
    )
    data = _request_json(urllib.request.Request(url))
    if not isinstance(data, dict):
        return {"status": "error", "results": [], "error": "searxng unreachable"}
    return {"status": "ok", "results": _normalize(data.get("results") or [], limit)}


def _read_env_file(path: str) -> dict:
    values = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key] = value
    except OSError:
        pass
    return values


def _tavily_api_key() -> str:
    return os.environ.get("TAVILY_API_KEY") or _read_env_file(TAVILY_ENV_FILE).get(
        "TAVILY_API_KEY", ""
    )


def search_tavily(query: str, limit: int = 5) -> dict:
    """Query Tavily, only when TAVILY_API_KEY is configured. Returns
    not_configured (not an error) when absent -- opt-in, never required."""
    api_key = _tavily_api_key()
    if not api_key:
        return {"status": "not_configured", "results": []}

    payload = json.dumps(
        {"api_key": api_key, "query": query, "max_results": limit}
    ).encode()
    req = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    data = _request_json(req)
    if not isinstance(data, dict):
        return {"status": "error", "results": [], "error": "tavily unreachable"}
    return {"status": "ok", "results": _normalize(data.get("results") or [], limit)}


def available_tools() -> list[str]:
    """Tool names this module currently advertises to the supervisor
    (`supervisor.yaml`'s `tools:` list) -- search.tavily only when a key
    is actually configured."""
    tools = ["search.searxng"]
    if _tavily_api_key():
        tools.append("search.tavily")
    return tools


def self_test() -> None:
    """ponytail: one runnable check -- JSON parsing/normalization, fail-soft
    on an unreachable endpoint (closed loopback port, same technique as
    memory.py's self-test), and the Tavily not_configured-without-key path."""
    global SEARXNG_ENDPOINT, TAVILY_ENV_FILE

    assert _normalize(
        [{"title": "a", "url": "http://x", "content": "c"}, "not-a-dict"], 5
    ) == [{"title": "a", "url": "http://x", "content": "c"}]

    old_endpoint = SEARXNG_ENDPOINT
    SEARXNG_ENDPOINT = "http://127.0.0.1:9"  # closed port: connection refused
    result = search_searxng("test")
    assert result["status"] == "error"
    assert result["results"] == []
    SEARXNG_ENDPOINT = old_endpoint

    old_env_file = TAVILY_ENV_FILE
    had_key = os.environ.pop("TAVILY_API_KEY", None)
    TAVILY_ENV_FILE = "/nonexistent/tavily.env"
    try:
        assert search_tavily("test") == {"status": "not_configured", "results": []}
        assert available_tools() == ["search.searxng"]
    finally:
        TAVILY_ENV_FILE = old_env_file
        if had_key is not None:
            os.environ["TAVILY_API_KEY"] = had_key

    print("search self_test: OK")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
