# dev-ai-continue

Continue.dev VSCode extension, pre-configured to use the LiteLLM gateway as
its LLM backend.

## What it does

- Installs the `Continue.continue` VSCode extension (idempotent).
- Drops a default `.continue/config.yaml` pointing at the LiteLLM endpoint.

## Build-time vs runtime split

`post-install.sh` is **build-time only**: it does NOT run `code
--install-extension` (network call, requires VSCode runtime). The original
scaffold did and would fail on every rebuild (no network at image-build
time, no `code` binary in the build root).

User installs the extension at first launch: `code --install-extension
Continue.continue --force`. All model calls still route through LiteLLM per
CLAUDE.md §7 via the dropped `config.yaml`.

## Dependencies

- `dev-editors` (VSCode must be available).
- `llm-litellm` (LiteLLM gateway at `http://127.0.0.1:4000`).

## Consumers

End user via VSCode. All model calls route through LiteLLM per CLAUDE.md §7.
