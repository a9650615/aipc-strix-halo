# dev-ai-opencode

OpenCode CLI — terminal AI coding tool, configured for LiteLLM.

## Install

```
distrobox enter node -- sudo npm install -g opencode-ai
```

## Configuration

Skel config at `/etc/skel/.config/opencode/config.json` points at LiteLLM.
Default model is `coder-agentic` (gemma4:26b) — **not** any qwen2.5-coder
alias (see below for why). `ornith-35b` is also registered as a second
option.

## Known issue: qwen2.5-coder tool calls are unreliable in this harness

Hardware-verified 2026-07-03: Ollama's streaming tool-call support is
broken for the qwen2 family — reproduced directly against Ollama's native
`/api/chat` with `stream:true` + `tools`, independent of LiteLLM or
OpenCode: the model's tool-call JSON leaks as plain streamed text content
instead of a structured `tool_calls` delta, regardless of model size
(reproduced on both `coder-fast`/7B and `coder-strong`/32B). Since OpenCode
streams by default, any `coder-*` tier will silently fail to invoke tools
— it just prints the raw JSON as if it were a chat reply.

`gemma4:26b` and `llama3.2:3b` both produce correctly structured
`tool_calls` in the identical test — this looks like a per-model-family
gap in Ollama's tool-call parser/template, not a general streaming bug or
a model-size/capability issue. `devstral:24b` (Mistral's dedicated
agentic-coding model) was also tried and rejected: across two attempts it
either silently skipped the tool call or refused outright even when
explicitly instructed to use it.

The `coder-fast`/`coder-strong`/`coder-thinking` qwen2.5 aliases were
removed from `models.yaml`/`llm-litellm` entirely 2026-07-04 (general
manifest trim, not specifically because of this issue) — this section
stays as the record of why they weren't the default while they existed,
and why any reintroduced qwen2.5-coder tier later should default to
`false` for OpenCode until re-verified.

Re-check when revisiting: has upstream Ollama fixed qwen2/qwen2.5
streaming tool-call parsing (no tracking issue number confirmed yet — the
closest known reports are `ollama/ollama#15457` and
`anomalyco/opencode#20995`, though those describe a related but distinct
symptom — index-always-0 for multiple simultaneous tool calls)?

## Dependencies

- `llm-litellm` (gateway at `http://127.0.0.1:4000`).
- `dev-distrobox-templates` (Node template).
- `llm-models` (registers `coder-agentic` -> `gemma4:26b` in the manifest
  `llm-ollama` pre-pulls from).
