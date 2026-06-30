# agent-orchestrator

LangGraph supervisor (D1) dispatching 4 sub-agents (D2):
- Researcher (default: `coder-fast`)
- Coder (default: `coder-strong`)
- Browser (default: `vlm-qwen2vl`)
- Daily Assistant (default: `intent-3b`)

## Dependencies
- llm-litellm (all LLM calls route through the gateway)
- agent-tools-search, agent-browser, agent-code-shell, agent-tools-files, agent-tools-calendar

## Spec
openspec/changes/phase-4-agent — tasks 2.1–2.7
