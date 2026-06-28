# llm-models

Canonical model registry mapping LiteLLM alias names (the public API surface
per `CLAUDE.md §7`) to concrete backends and on-disk weight locations. The
single source of truth for "what does `coder-strong` actually run?"

## What it does

- Installs `/etc/aipc/models/models.yaml` listing every logical model alias,
  its backend (`ollama`, `lemonade`, or `vllm`), its concrete `model_id`, and
  its approximate on-disk size.
- `llm-litellm` reads this file at startup to render its router config.
- `llm-ollama` and `llm-lemonade` use it to decide which weights to pull /
  compile.

## Dependencies

- `system-base` (yaml parser available for `aipc models sync`).
- `ai-rocm`, `ai-xdna` (backends must be healthy before weights matter).

## Consumers

- `llm-litellm` (renders router config from this file).
- `llm-ollama` (pre-pulls weights listed here).
- `llm-lemonade` (pre-compiles NPU models listed here).
- `aipc models sync` CLI.

## Update policy

Adding a new logical model = append one YAML entry and (if the backend is
Ollama) the matching model name in `llm-ollama`'s pull manifest. No other
code changes. See `CLAUDE.md §7`.
