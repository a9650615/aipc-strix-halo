# agent-tools-usage

Callable usage/quota tools for the **local aipc assistant** (Daily Assistant
LangGraph tools), not a human GUI.

## What the assistant gets

```python
from aipc_agent_tools_usage import lookup_usage

lookup_usage("claude")
# → {"status": "ok", "tool": "usage.lookup", "providers": [
#      {"id": "claude", "used_percent": 42.0, "reset": "in 3h", "status": "ok"},
#    ]}
```

Backend resolution (first hit wins):

1. `codexbar_usage.fetch` (if `dev-ai-codexbar-usage` is installed)
2. `GET http://127.0.0.1:8080/usage` (if `aipc usage serve` / GUI server is up)
3. `aipc-usage usage -f json` on PATH
4. `not_configured` (fail soft — graph does not crash)

Perfect CodexBar parity is **out of scope**. The goal is “assistant can answer
how much Claude/Codex quota is left.”

## Wiring

- Package path: `/usr/lib/aipc-agent/aipc_agent_tools_usage/`
- Imported by `agent-orchestrator` `daily_assistant.usage_lookup` `@tool`
- Orchestrator venv sees this via existing `aipc-agent.pth` (same as files/search)

## GUI

Tray GUI lives in `dev-ai-codexbar-gui` and is optional; it is not required for
the assistant tool path.

## Verification

```sh
./modules/agent-tools-usage/verify.sh   # static + self-test
```
