# CodexBar Usage — Supported Providers

This document lists all providers registered in the catalog (`registry.py`).
Each entry shows the canonical ID, display name, auth method, Linux support
level, and the environment variables used for authentication.

## Provider Table

| ID | Name | Auth | Source | Linux | Key Env Vars |
|----|------|------|--------|-------|--------------|
| `codex` | Codex | api_key | api | full | `OPENAI_ADMIN_KEY`, `OPENAI_API_KEY` |
| `openai` | OpenAI | api_key | api | full | `OPENAI_ADMIN_KEY`, `OPENAI_API_KEY` |
| `claude` | Claude | api_key | api | full | `ANTHROPIC_ADMIN_KEY`, `ANTHROPIC_API_KEY` |
| `gemini` | Gemini | api_key | api | full | `GEMINI_API_KEY`, `GOOGLE_API_KEY` |
| `copilot` | GitHub Copilot | cookie | cookie | full | `GITHUB_TOKEN`, `COPILOT_API_TOKEN` |
| `cursor` | Cursor | cookie | cookie | full | `CURSOR_TOKEN` |
| `windsurf` | Windsurf | cookie | cookie | full | `WINDSURF_TOKEN` |
| `zed` | Zed | cookie | cookie | full | `ZED_TOKEN` |
| `jetbrains` | JetBrains AI | api_key | api | full | `JETBRAINS_API_KEY` |
| `opencode` | OpenCode | api_key | api | full | `OPENCODE_API_KEY` |
| `kiro` | Kiro | cookie | cookie | full | `KIRO_TOKEN` |
| `augment` | Augment | api_key | api | full | `AUGMENT_API_KEY` |
| `amp` | Amp | api_key | api | full | `AMP_API_KEY` |
| `zai` | z.ai | api_key | api | full | `Z_AI_API_KEY` |
| `deepseek` | DeepSeek | api_key | api | full | `DEEPSEEK_API_KEY`, `DEEPSEEK_KEY` |
| `grok` | Grok | api_key | api | **partial** | `XAI_API_KEY`, `GROK_API_KEY` |
| `moonshot` | Moonshot | api_key | api | full | `MOONSHOT_API_KEY` |
| `venice` | Venice | api_key | api | full | `VENICE_API_KEY` |
| `openrouter` | OpenRouter | api_key | api | full | `OPENROUTER_API_KEY` |
| `groq` | GroqCloud | api_key | api | full | `GROQ_API_KEY` |
| `elevenlabs` | ElevenLabs | api_key | api | full | `ELEVENLABS_API_KEY` |
| `warp` | Warp | api_key | api | full | `WARP_API_KEY` |
| `poe` | Poe | api_key | api | full | `POE_API_KEY` |
| `chutes` | Chutes | api_key | api | full | `CHUTES_API_KEY` |
| `codebuff` | Codebuff | api_key | api | full | — |
| `croft` | Croft | api_key | api | full | — |
| `alibaba` | Alibaba Coding | api_key | api | full | — |
| `alibabatokenplan` | Alibaba Token | api_key | api | full | — |
| `minimax` | MiniMax | api_key | api | full | — |
| `kimi` | Kimi | api_key | api | full | — |
| `kimik2` | Kimi K2 | api_key | api | full | — |
| `kilo` | Kilo | api_key | api | full | — |
| `doubao` | Doubao | api_key | api | full | — |
| `synthetic` | Synthetic | none | builtin | full | — |
| `crossmodel` | CrossModel | none | builtin | full | — |
| `manus` | Manus | api_key | api | full | — |
| `llmproxy` | LLM Proxy | api_key | api | full | `LLM_PROXY_API_KEY` |
| `litellm` | LiteLLM | api_key | api | full | `LITELLM_API_KEY`, `LITELLM_PROXY_KEY` |
| `clawrouter` | ClawRouter | api_key | api | full | `CLAWROUTER_API_KEY` |
| `deepgram` | Deepgram | api_key | api | full | — |
| `azureopenai` | Azure OpenAI | api_key | api | full | — |
| `bedrock` | AWS Bedrock | oauth | api | full | — |
| `vertexai` | Vertex AI | oauth | api | full | — |
| `antigravity` | Antigravity | api_key | api | full | — |
| `ollama` | Ollama | none | builtin | full | — |
| `perplexity` | Perplexity | api_key | api | full | — |
| `mistral` | Mistral | api_key | api | full | — |
| `abacus` | Abacus AI | api_key | api | full | — |
| `sakana` | Sakana AI | api_key | api | full | — |
| `stepfun` | StepFun | api_key | api | full | — |
| `qoder` | Qoder | api_key | api | full | — |
| `devin` | Devin | api_key | api | full | — |
| `commandcode` | Command Code | api_key | api | full | — |
| `t3chat` | T3 Chat | api_key | api | full | — |
| `mimo` | MiMo | api_key | api | full | — |
| `factory` | Factory | api_key | api | full | — |
| `opencodego` | OpenCode Go | api_key | api | full | — |

## Auth Types

| Type | Description |
|------|-------------|
| `api_key` | Bearer token or API key in Authorization header |
| `cookie` | Browser cookie-based authentication |
| `oauth` | OAuth 2.0 flow (AWS Bedrock, Vertex AI) |
| `builtin` | No auth needed (local models like Ollama) |
| `none` | Synthetic/built-in placeholder |

## Source Types

| Type | Description |
|------|-------------|
| `api` | REST API endpoint |
| `cookie` | Browser cookie parsing |
| `jsonl` | Local JSONL log scanning |
| `dashboard` | Web dashboard scraping |
| `builtin` | Built-in/local (no external auth) |

## Linux Support Levels

| Level | Meaning |
|-------|---------|
| `full` | Works on Linux without modifications |
| `partial` | Partially works (e.g., Grok CLI works; web fallback needs browser) |
| `none` | Not supported on Linux (none currently) |

## Implemented Providers (with fetchers)

The following providers have dedicated fetcher modules in `providers/`:

| Provider | Module | API Endpoint |
|----------|--------|--------------|
| OpenAI | `providers/openai.py` | `GET https://api.openai.com/v1/organization/cost_report` |
| Claude | `providers/claude.py` | `GET https://api.anthropic.com/v1/account`, `GET .../v1/messages` |
| DeepSeek | `providers/deepseek.py` | `GET https://api.deepseek.com/balance` |
| Gemini | `providers/gemini.py` | `GET https://content-aio.googleapis.com/v1/models` |
| Copilot | `providers/copilot.py` | `GET https://api.github.com/copilot_internal/user` |
| Grok | `providers/grok.py` | CLI: `grok agent stdio` → JSON-RPC `x.ai/billing` |
| LiteLLM | `providers/litellm.py` | `GET {proxy}/v1/key/info`, `GET .../v1/user/info` |
| OpenRouter | `providers/openrouter.py` | `GET https://openrouter.ai/api/v1/key/info`, `GET .../v1/auth/key` |

## Status URLs

| Provider | Status Page |
|----------|-------------|
| OpenAI / Codex | https://status.openai.com |
| Claude / Anthropic | https://status.anthropic.com |
| Gemini / Google | https://status.cloud.google.com |
| GitHub / Copilot | https://www.githubstatus.com |
| OpenRouter | https://status.openrouter.ai |
| Grok / xAI | — |
