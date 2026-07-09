# dev-ai-codexbar-usage

AI coding usage tracker — a Python port of the CodexBar Swift tool, tracking
rate windows, costs, and identity for 60+ AI coding providers on Linux.

Ported from: [CodexBar](https://github.com/steipete/CodexBar) (`Sources/CodexBarCore/`).
Mirrors the original Swift source line-by-line where feasible; the Python module
lives under `codexbar_usage/` and ships as the `aipc-usage` CLI.

## Features

- **60+ providers** in the registry: Codex, Claude, OpenAI, Gemini, Copilot,
  Cursor, Windsurf, Zed, JetBrains AI, Grok, OpenRouter, DeepSeek, LiteLLM,
  and many more.
- **Provider-specific fetchers** with retry logic, auth headers, and error
  taxonomy (`AuthError`, `NetworkError`, `ConfigError`).
- **Three output formats**: cards (rich panels), table (rich table), JSON
  (pretty-printed).
- **Cost scanning** via local JSONL logs from Codex and Claude CLI sessions.
- **HTTP server** (`serve` command) exposing `/health`, `/usage`, `/cost` for
  waybar / GNOME / KDE extensions.
- **Config management**: enable/disable providers, set API keys, validate
  config file — all via CLI subcommands.
- **XDG-compliant** config storage at `~/.config/codexbar/config.json`.
- **Environment variable overrides** for API keys (`CODEXBAR_<PROVIDER>_API_KEY`,
  plus provider-specific fallbacks like `OPENAI_ADMIN_KEY`, `ANTHROPIC_API_KEY`,
  etc.).

## Installation

Built as part of the `dev-ai-codexbar-usage` module in the aipc project.
`aipc doctor` runs this module's `verify.sh`. Render targets (bootc + ansible)
include the module whenever it is present under `modules/` (no `.disabled`).

```sh
# From the project root — the module installs itself into the aipc venv.
tools/aipc render bootc   # builds the container image
tools/aipc render ansible --check   # validates the ansible render
```

Once the image is running (or after `pip install -e` of the package tree):

```sh
# Preferred aipc entrypoints
aipc usage show -p claude,openai
aipc usage cost --days 30
aipc usage serve --port 8080
aipc usage gui
aipc usage providers
aipc usage config --help

# Direct module CLI (same package)
aipc-usage --help
python -m codexbar_usage --help
```

Optional always-on HTTP server (user session):

```sh
systemctl --user enable --now aipc-usage.service
```

## Quick Start

```sh
# Show usage for all providers
aipc usage show
aipc-usage usage

# Filter by provider
aipc usage show -p claude,openai,gemini

# JSON output
aipc usage show -p claude -f json

# Start HTTP server for tray / waybar
aipc usage serve --port 8080

# Manage providers
aipc usage config enable -- claude
aipc-usage config set-api-key -p claude --api-key "sk-ant-admin-..."
aipc-usage config validate
aipc-usage config dump

# LiteLLM proxy DB plane (local gateway spend)
aipc usage list
aipc usage aggregate
```

## Configuration

Configuration is stored at `~/.config/codexbar/config.json` (XDG-compliant).
See `config.md` for the full schema and environment variable reference.

Key config file: `files/etc/aipc/codexbar-usage/config.yaml` (module-level
defaults: `db_path`, `default_format`, `visible_providers`).

## CLI Reference

| Command | Description |
|---------|-------------|
| `aipc-usage usage` | Show usage data for AI coding providers |
| `aipc-usage cost` | Show local token cost usage (JSONL scans) |
| `aipc-usage serve` | Start HTTP server for usage/cost JSON |
| `aipc-usage config enable <id>` | Enable a provider |
| `aipc-usage config disable <id>` | Disable a provider |
| `aipc-usage config set-api-key` | Set API key for a provider |
| `aipc-usage config validate` | Validate config file |
| `aipc-usage config dump` | Print normalized config JSON |
| `aipc-usage cache clear` | Clear local caches |

## Supported Providers

See [providers.md](providers.md) for the full list with auth methods,
environment variables, Linux support status, and API endpoints.

## Linux Support

- **Implemented fetchers** (wired into CLI + `serve`): Codex, OpenAI, Claude,
  Gemini, Copilot, Cursor, Windsurf, Zed, DeepSeek, Moonshot, Kimi, OpenRouter,
  Grok, Warp, LiteLLM.
- **Registry-only**: remaining catalog entries return `not-implemented` until a
  fetcher lands under `providers/`.
- **Partial**: Grok/web and cookie providers need credentials on disk; without
  them the status is `no-api-key` / `error` rather than fake zeros.

## Architecture

```
codexbar_usage/
├── __init__.py          # Package root, version
├── cli.py               # Click CLI (usage, cost, serve, config, cache)
├── config.py            # Config read/write, provider enable/disable, API key resolve
├── fetch.py             # Shared provider dispatch (CLI + HTTP)
├── cost.py              # Local Codex/Claude JSONL cost scans
├── registry.py          # Provider catalog + fetch_plan metadata
├── server.py            # HTTP server (ThreadingHTTPServer, /health /usage /cost)
├── ui.py                # Terminal renderers (cards, table, JSON)
├── provider_aliases.py  # LiteLLM alias map (must NOT be named providers.py)
├── __main__.py          # python -m codexbar_usage entry point
└── providers/           # Real BaseProvider implementations
    ├── __init__.py      # PROVIDER_MODULE_MAP + instantiate_provider()
    ├── base.py
    ├── claude.py / openai.py / openai_codex.py / ...
    └── litellm.py / openrouter.py / ...
```


## Testing

```sh
cd modules/dev-ai-codexbar-usage
pip install -e "files/usr/lib/aipc-codexbar-usage[dev]" pytest
pytest tests/ -v
```

## Module Integration

- **Bootc**: `Containerfile` COPY + `post-install.sh` pip-installs into the
  aipc venv.
- **Ansible**: `modules/dev-ai-codexbar-usage/` is referenced from the
  playbook; renders identically to the bootc target.
- **Verify**: `verify.sh` checks the package is importable from the aipc venv.
