# CodexBar Usage — Configuration Reference

Configuration lives at `~/.config/codexbar/config.json`. The module also honors
the XDG config path (`$XDG_CONFIG_HOME/codexbar/config.json`) and the legacy
path (`~/.codexbar/config.json`).

## config.json Schema

```jsonc
{
  "version": 1,

  "providers": [
    {
      "id": "claude",
      "enabled": true,
      "source": "auto",
      "cookie_source": "auto",
      "cookie_header": null,
      "apiKey": "sk-ant-admin-...",
      "enterpriseHost": null,
      "region": null,
      "workspaceID": null,
      "tokenAccounts": []
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `version` | int | Config file version (currently 1). |
| `providers` | array | List of provider configurations. |
| `providers[].id` | string | Canonical provider ID (required, matches registry). |
| `providers[].enabled` | bool | Whether the provider is active. Default: `true`. |
| `providers[].source` | string | Auth source strategy. Default: `"auto"`. |
| `providers[].cookie_source` | string | Cookie auth source. Default: `"auto"`. |
| `providers[].cookie_header` | string \| null | Raw cookie header value. |
| `providers[].apiKey` | string \| null | API key for the provider. |
| `providers[].enterpriseHost` | string \| null | Enterprise host (e.g. Azure OpenAI). |
| `providers[].region` | string \| null | Region override. |
| `providers[].workspaceID` | string \| null | Workspace ID. |
| `providers[].tokenAccounts` | array | Token account entries. |

## Environment Variables

The module resolves API keys from three sources in order:

1. `providers[].apiKey` in `config.json`
2. `CODEXBAR_<PROVIDER>_API_KEY` (e.g. `CODEXBAR_CLAUDE_API_KEY`)
3. Provider-specific fallback variables

### Global

| Variable | Description |
|----------|-------------|
| `CODEXBAR_CONFIG` | Override the config directory path. |
| `XDG_CONFIG_HOME` | XDG config base (defaults to `~/.config`). |

### Per-provider API key variables

| Provider | Primary | Fallback |
|----------|---------|----------|
| OpenAI | `OPENAI_ADMIN_KEY` | `OPENAI_API_KEY` |
| Claude | `ANTHROPIC_ADMIN_KEY` | `ANTHROPIC_API_KEY` |
| Gemini | `GEMINI_API_KEY` | `GOOGLE_API_KEY` |
| Copilot | `GITHUB_TOKEN` | `COPILOT_API_TOKEN` |
| DeepSeek | `DEEPSEEK_API_KEY` | `DEEPSEEK_KEY` |
| Moonshot | `MOONSHOT_API_KEY` | — |
| OpenRouter | `OPENROUTER_API_KEY` | — |
| Groq | `GROQ_API_KEY` | — |
| ElevenLabs | `ELEVENLABS_API_KEY` | — |
| z.ai | `Z_AI_API_KEY` | — |
| Venice | `VENICE_API_KEY` | — |
| Warp | `WARP_API_KEY` | — |
| Poe | `POE_API_KEY` | — |
| Chutes | `CHUTES_API_KEY` | — |
| LiteLLM | `LITELLM_API_KEY` | `LITELLM_PROXY_KEY` |
| LLM Proxy | `LLM_PROXY_API_KEY` | — |
| ClawRouter | `CLAWROUTER_API_KEY` | — |
| Codex | `CODEXBAR_CODEX_API_KEY` | `OPENAI_ADMIN_KEY`, `OPENAI_API_KEY` |

## Module-Level Defaults

`files/etc/aipc/codexbar-usage/config.yaml`:

```yaml
# Path to the LiteLLM proxy SQLite database.
db_path: /var/lib/litellm-proxy/litellm_proxy.db

# Default output format when --format is omitted.
default_format: table

# Providers to show by default (empty = all).
visible_providers: []
```

## Config CLI

```sh
# Show current config
aipc-usage config dump

# Validate config file
aipc-usage config validate

# Enable/disable providers
aipc-usage config enable claude
aipc-usage config disable copilot

# Set API key (from argument)
aipc-usage config set-api-key -p claude --api-key "sk-ant-admin-..."

# Set API key (from stdin, useful for CI)
echo "sk-ant-admin-..." | aipc-usage config set-api-key -p claude --stdin

# Clear caches
aipc-usage cache clear --all
aipc-usage cache clear --cookies
aipc-usage cache clear --cost
```

## Example: Minimal Config

```json
{
  "version": 1,
  "providers": [
    {
      "id": "claude",
      "enabled": true,
      "apiKey": "sk-ant-admin-..."
    },
    {
      "id": "openai",
      "enabled": true,
      "apiKey": "sk-ant-admin-..."
    }
  ]
}
```

## Example: Full Config with All Providers

```json
{
  "version": 1,
  "providers": [
    {
      "id": "codex",
      "enabled": true,
      "source": "auto",
      "apiKey": null
    },
    {
      "id": "openai",
      "enabled": true,
      "source": "auto",
      "apiKey": "sk-ant-admin-..."
    },
    {
      "id": "claude",
      "enabled": true,
      "source": "auto",
      "apiKey": "sk-ant-admin-..."
    },
    {
      "id": "gemini",
      "enabled": true,
      "source": "auto",
      "apiKey": null
    },
    {
      "id": "copilot",
      "enabled": false,
      "source": "auto",
      "apiKey": null
    }
  ]
}
```
