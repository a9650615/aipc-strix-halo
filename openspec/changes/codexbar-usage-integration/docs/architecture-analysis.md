# CodexBar Architecture Analysis Report

**Date**: 2026-07-08
**Source**: [steipete/CodexBar](https://github.com/steipete/CodexBar) (v0.41.0, 3,317 commits)
**Purpose**: Python port preparation — provider fetcher logic, API endpoints, auth methods, and Linux compatibility assessment.

---

## 1. High-Level Architecture

### 1.1 Project Structure

```
Sources/
├── CodexBarCore/          # Core library — providers, fetchers, parsing, shared utilities
│   ├── Providers/         # 57 provider implementations (one folder per provider)
│   ├── Host APIs/         # BrowserCookieAPI, KeychainAPI, PTYAPI, HTTPAPI, etc.
│   └── [Core utilities]
├── CodexBarCLI/           # CLI binary — `codexbar` command
├── CodexBar/              # macOS app (status item, SwiftUI, Sparkle updates)
├── CodexBarWidget/        # WidgetKit extension
├── CodexBarClaudeWatchdog/ # Claude PTY session watchdog
└── CodexBarClaudeWebProbe/ # Claude web fetch diagnostic helper
```

### 1.2 Data Flow

```
Background refresh (UsageStore)
  → ProviderDescriptor (compile-time enum)
    → ProviderFetchPipeline (ordered strategy list)
      → ProviderFetchStrategy (individual fetcher)
        → Host API (HTTP, PTY, WebView, Local File, Browser Cookies, Keychain)
  → UsageSnapshot (primary/secondary/tertiary RateWindows + identity + cost)
  → CLI output / HTTP serve JSON
```

### 1.3 Key Abstractions

| Abstraction | Description |
|---|---|
| `UsageProvider` | Enum of all 57 provider IDs. Compile-time constant. |
| `ProviderDescriptor` | Source of truth: labels, URLs, branding, fetch plan, CLI config. |
| `ProviderFetchStrategy` | Single fetch path (CLI, web, oauth, api, local). |
| `ProviderFetchPipeline` | Ordered list of strategies, resolved at runtime. |
| `ProviderRuntime` | `.app` (macOS GUI) or `.cli` (Linux/headless). |
| `ProviderSourceMode` | `.auto` / `.cli` / `.web` / `.oauth` / `.api` |
| `UsageSnapshot` | Result: primary/secondary/tertiary `RateWindow` + `ProviderIdentitySnapshot` + optional cost. |
| `RateWindow` | `usedPercent` + `windowMinutes` + `resetsAt` + `resetDescription`. |
| `ProviderMetadata` | Display labels, dashboard URLs, status pages, default enablement. |
| `ProviderBranding` | Icon style, color, resource name. |
| `CodexBarConfig` | JSON config file: providers array, API keys, cookies, settings. |

---

## 2. Config File Format

### 2.1 Location (XDG-compliant)

- `CODEXBAR_CONFIG` env var (highest priority)
- `$XDG_CONFIG_HOME/codexbar/config.json` (XDG)
- `~/.config/codexbar/config.json` (default new install)
- `~/.codexbar/config.json` (legacy path)

### 2.2 Schema

```json
{
  "version": 1,
  "providers": [
    {
      "id": "codex",
      "enabled": true,
      "source": "auto",
      "cookieSource": "auto",
      "cookieHeader": null,
      "apiKey": null,
      "enterpriseHost": null,
      "region": null,
      "workspaceID": null,
      "tokenAccounts": null
    }
  ]
}
```

### 2.3 Field Definitions

| Field | Description |
|---|---|
| `id` | Provider identifier (required, from `UsageProvider` enum) |
| `enabled` | Enable/disable toggle |
| `source` | Preferred fetch mode: `auto`, `web`, `cli`, `oauth`, `api` |
| `cookieSource` | Cookie policy: `auto` (browser import), `manual`, `off` |
| `cookieHeader` | Raw HTTP `Cookie:` header value |
| `apiKey` | API token for API-backed providers |
| `enterpriseHost` | Base URL override (for LLM Proxy, LiteLLM, etc.) |
| `region` | Provider-specific region (e.g. `zai`, `minimax`) |
| `workspaceID` | Provider workspace/deployment/project ID |
| `tokenAccounts` | Multi-account token array |

### 2.4 Token Account Schema

```json
{
  "activeIndex": 0,
  "accounts": [
    {
      "id": "uuid",
      "label": "user@example.com",
      "token": "sk-...",
      "addedAt": 1735123456,
      "lastUsed": 1735220000
    }
  ]
}
```

### 2.5 Environment Variable Overrides

Most providers also accept env var overrides (documented per-provider). Key examples:

- `OPENAI_ADMIN_KEY`, `OPENAI_API_KEY`
- `ANTHROPIC_ADMIN_KEY`
- `COPILOT_API_TOKEN`
- `Z_AI_API_KEY`, `Z_AI_API_HOST`
- `ELEVENLABS_API_KEY`
- `DEEPSEEK_API_KEY`, `DEEPSEEK_KEY`
- `MOONSHOT_API_KEY`
- `OPENROUTER_API_KEY`
- `GROQ_API_KEY`
- `LLM_PROXY_API_KEY`, `LLM_PROXY_BASE_URL`
- `LITELLM_API_KEY`, `LITELLM_BASE_URL`
- `CLAWROUTER_API_KEY`, `CLAWROUTER_BASE_URL`
- `DEEPGRAM_API_KEY`
- `WARP_API_KEY`
- `AWS_*` (Bedrock)
- `MANUS_SESSION_TOKEN`, `MANUS_COOKIE`
- `KIMI_CODE_API_KEY`
- `KIMI_AUTH_TOKEN`
- `WINDSURF_*`
- `ALIBABA_CODING_PLAN_API_KEY`
- `ALIBABA_TOKEN_PLAN_COOKIE`

---

## 3. Complete Provider Catalog

### 3.1 Primary Providers (High Priority)

| # | Provider | ID | Strategies | Auth Method | API Endpoint | Linux |
|---|---|---|---|---|---|---|
| 1 | **Codex** | `codex` | OAuth → CLI RPC | OAuth (device flow) / CLI | `codex app-server` JSON-RPC (`account/read`, `account/rateLimits/read`) | `full` + `partial` |
| 2 | **OpenAI** | `openai` | Admin API key | API key | `GET /v1/organization/cost_report`, `GET /v1/organization/usage_report/messages` | `full` |
| 3 | **Claude** | `claude` | Admin API → OAuth → CLI PTY → Web | Admin API key / OAuth / CLI / Cookies | `GET /v1/organizations/cost_report`, `GET /v1/organizations/usage_report/messages` | `partial` (no CLI PTY) |
| 4 | **Gemini** | `gemini` | OAuth via Gemini CLI | OAuth (Gemini CLI credentials) | `retrieveUserQuota` API | `partial` |
| 5 | **Copilot** | `copilot` | Device flow + API | GitHub device flow OAuth | `GET /copilot_internal/user` (api.github.com) | `full` |

### 3.2 Major IDE / Coding Provider

| # | Provider | ID | Strategies | Auth Method | API Endpoint | Linux |
|---|---|---|---|---|---|---|
| 6 | **Cursor** | `cursor` | Browser cookies | Web cookies (cursor.com) | Internal API via cookies | `partial` (no browser import) |
| 7 | **Windsurf** | `windsurf` | Browser localStorage / SQLite | Web cookies / local SQLite | Internal API via cookies | `partial` (no browser import) |
| 8 | **Zed** | `zed` | Keychain session | macOS Keychain + API | `GET /client/users/me` (cloud.zed.dev) | `partial` (no Keychain) |
| 9 | **JetBrains AI** | `jetbrains` | Local XML file | Local file read | `AIAssistantQuotaManager2.xml` | `full` |
| 10 | **Cursor (Go)** | `opencodego` | Web cookies / SQLite | Web cookies / local DB | Web + `opencode.db` | `full` |
| 11 | **OpenCode** | `opencode` | Browser cookies | Web cookies (opencode.ai) | Internal API | `partial` (no browser import) |
| 12 | **Kiro** | `kiro` | CLI command | `kiro-cli chat --no-interactive "/usage"` | CLI subprocess | `full` |
| 13 | **Augment** | `augment` | Augment CLI / cookies | `auggie` CLI / browser cookies | CLI + internal API | `partial` |
| 14 | **Amp** | `amp` | Local `amp usage` / API / cookies | CLI / API / browser cookies | `amp usage` CLI | `full` |

### 3.3 API-Key-Only Providers

| # | Provider | ID | Strategies | Auth Method | API Endpoint | Linux |
|---|---|---|---|---|---|---|
| 15 | **z.ai** | `zai` | API token | API key (config/env) | Quota API (z.ai / Bailian) | `full` |
| 16 | **DeepSeek** | `deepseek` | API token | API key | `GET /v1/users/me/balance` | `full` |
| 17 | **Moonshot** | `moonshot` | API key | API key | `GET /v1/users/me/balance` | `full` |
| 18 | **Venice** | `venice` | API key | API key | DIEM/USD balance API | `full` |
| 19 | **OpenRouter** | `openrouter` | API token | API key | Credits + rate-limit API | `full` |
| 20 | **GroqCloud** | `groq` | API key | API key | Prometheus metrics API (Enterprise Prometheus) | `full` |
| 21 | **ElevenLabs** | `elevenlabs` | API key | API key | `GET /v1/user/subscription` (api.elevenlabs.io) | `full` |
| 22 | **Warp** | `warp` | API key | API key | GraphQL request limits API | `full` |
| 23 | **Poe** | `poe` | API key | API key | Points balance API | `full` |
| 24 | **Chutes** | `chutes` | API key | API key | `api.chutes.ai` subscription + quota APIs | `full` |
| 25 | **Codebuff** | `codebuff` | API token / credentials.json | API key / `~/.config/manicode/credentials.json` | Usage API | `full` |
| 26 | **Crof** | `croft` | API key | API key | `GET https://crof.ai/usage_api/` | `full` |
| 27 | **Alibaba Coding Plan** | `alibaba` | Web cookies / API key | Console RPC / API key | Alibaba console RPC | `partial` |
| 28 | **Alibaba Token Plan** | `alibabatokenplan` | Web cookies | Browser cookies | Bailian `GetSubscriptionSummary` API | `partial` |
| 29 | **MiniMax** | `minimax` | API token / web cookies | API key / browser cookies | Internal API | `full` (api), `partial` (web) |
| 30 | **Kimi** | `kimi` | API key / auth cookie | API key / JWT cookie | Internal API | `full` |
| 31 | **Kimi K2** | `kimik2` | API key | API key | Legacy credit endpoint | `full` |
| 32 | **Kilo** | `kilo` | API token / CLI auth | API key / `~/.local/share/kilo/auth.json` | Usage API | `full` |
| 33 | **Doubao** | `doubao` | API key | API key | Volcengine Ark chat-completions | `full` |
| 34 | **Synthetic** | `synthetic` | API key | API key | Quota API | `full` |
| 35 | **CrossModel** | `crossmodel` | API key | API key | `/v1/credits`, `/v1/usage` | `full` |
| 36 | **Manus** | `manus` | Browser session / manual token | Browser cookie / manual Bearer | `POST /user.v1.UserService/GetAvailableCredits` (api.manus.im) | `partial` |

### 3.4 Proxy / Aggregator Providers

| # | Provider | ID | Strategies | Auth Method | API Endpoint | Linux |
|---|---|---|---|---|---|---|
| 37 | **LLM Proxy** | `llmproxy` | API key + base URL | API key | `GET /v1/quota-stats` (custom base URL) | `full` |
| 38 | **LiteLLM** | `litellm` | API key + base URL | API key | `/key/info`, `/user/info`, `/team/info` | `full` |
| 39 | **ClawRouter** | `clawrouter` | API key + optional base URL | API key | `GET /v1/usage` (clawrouter.openclaw.ai or custom) | `full` |

### 3.5 Browser-Cookie Providers

| # | Provider | ID | Strategies | Auth Method | API Endpoint | Linux |
|---|---|---|---|---|---|---|
| 40 | **Cursor** | `cursor` | Web cookies | Browser cookies | Internal API | `partial` |
| 41 | **Windsurf** | `windsurf` | Web localStorage / SQLite | Browser cookies / local SQLite | Internal API | `partial` |
| 42 | **Cursor (Zed)** | `zed` | Keychain | macOS Keychain | cloud.zed.dev API | `partial` |
| 43 | **OpenCode** | `opencode` | Web cookies | Browser cookies | Internal API | `partial` |
| 44 | **Cursor (Factory)** | `factory` | Web cookies / tokens / WorkOS | Browser cookies / bearer tokens | Factory internal API | `partial` |
| 45 | **Devin** | `devin` | Chrome localStorage / manual Bearer | Browser localStorage / manual | `GET /api/<org-id>/billing/quota/usage` | `partial` |
| 46 | **Command Code** | `commandcode` | Web cookies | Browser cookies | `api.commandcode.ai` | `partial` |
| 47 | **T3 Chat** | `t3chat` | Web cookies | Browser cookies | `GET /api/trpc/getCustomerData` (t3.chat) | `partial` |
| 48 | **Ollama** | `ollama` | API key + browser cookies | API key / browser cookies | Internal API | `full` (api), `partial` (web) |
| 49 | **Perplexity** | `perplexity` | Browser cookies / manual token | Browser cookies / manual token | Credits API | `partial` |
| 50 | **MiMo** | `mimo` | Browser cookies | Browser cookies | Balance + token plan endpoints | `partial` |
| 51 | **Mistral** | `mistral` | Browser cookies | Browser cookies | admin.mistral.ai, console.mistral.ai | `partial` |
| 52 | **Abacus AI** | `abacus` | Browser cookies | Browser cookies | Compute points + billing API | `partial` |
| 53 | **Sakana AI** | `sakana` | Manual cookie header | Manual cookie | Billing page parser | `partial` |
| 54 | **StepFun** | `stepfun` | Username/password / manual token | Browser login / manual | `platform.stepfun.com` | `partial` |
| 55 | **Qoder** | `qoder` | Chrome cookies / manual | Browser cookies / manual header | qoder.com dashboard | `partial` |

### 3.6 Cloud / Infra Providers

| # | Provider | ID | Strategies | Auth Method | API Endpoint | Linux |
|---|---|---|---|---|---|---|
| 56 | **AWS Bedrock** | `bedrock` | AWS credentials / profile | AWS keys / named profile | AWS Cost Explorer, CloudWatch | `full` |
| 57 | **Vertex AI** | `vertexai` | gcloud OAuth | Google ADC (gcloud) | Cloud Monitoring quota metrics | `partial` |
| 58 | **Deepgram** | `deepgram` | API key | API key | Usage breakdown API | `full` |
| 59 | **Azure OpenAI** | `azureopenai` | API key + endpoint | API key + endpoint URL | Azure chat-completions probe | `full` |

### 3.7 Local Probe Providers

| # | Provider | ID | Strategies | Auth Method | API Endpoint | Linux |
|---|---|---|---|---|---|---|
| — | **Antigravity** | `antigravity` | Local LSP probe | None (local HTTP) | Localhost HTTPS (Antigravity LSP) | `full` |

---

## 4. Linux Compatibility Assessment

### 4.1 Legend

- **`full`** — Can be fully implemented on Linux; no macOS-specific dependencies
- **`partial`** — Partial support; core API works but browser cookie import or Keychain is macOS-only
- **`not-supported`** — Requires macOS-specific framework (Keychain, WebView, WidgetKit, etc.)

### 4.2 Provider Linux Status Summary

| Linux Status | Count | Providers |
|---|---|---|
| **`full`** | 22 | OpenAI, DeepSeek, Moonshot, Venice, OpenRouter, GroqCloud, ElevenLabs, Warp, Poe, Chutes, Codebuff, Crof, MiniMax (api), Kimi, KimiK2, Kilo, Doubao, Synthetic, CrossModel, LLM Proxy, LiteLLM, ClawRouter, Deepgram, Azure OpenAI, AWS Bedrock, JetBrains AI, Kiro, Amp, Ollama (api), Antigravity |
| **`partial`** | 35 | Codex (CLI only), Claude (no PTY), Gemini (limited), Copilot (no device flow UI), Cursor, Windsurf, Zed, OpenCode, Factory, Devin, Command Code, T3 Chat, Perplexity, MiMo, Mistral, Abacus, Sakana, StepFun, Qoder, Manus, Alibaba Coding/Token, Ollama (web), Vertex AI, Augment, Amp (web) |
| **`not-supported`** | 0 | (None — all providers work at least partially on Linux via the CLI binary) |

### 4.3 macOS-Specific Features to Replace

| macOS Feature | Replacement on Linux |
|---|---|
| **Keychain access** | Not available; use env vars / config file / manual token entry |
| **Browser cookie import (Safari/Chrome/Firefox)** | Use `SweetCookieKit` with Linux-compatible backends, or manual cookie paste |
| **WebView (WKWebView)** | Use headless HTTP client instead of JS evaluation |
| **WidgetKit** | Not available; serve JSON via `codexbar serve` for waybar/GNOME extensions |
| **Sparkle auto-updates** | Use system package manager |
| **Device flow OAuth (browser popup)** | CLI-based device flow with manual URL copy-paste |
| **PTY session management** | Use subprocess management (already done in CLI builds) |

### 4.4 Already Linux-Ready Components

- **`CodexBarCLI`** — Already built and distributed for Linux (glibc + musl)
- **`codexbar serve`** — Local HTTP server for external integrations
- **`codexbar usage`** — Text/JSON output for all API-based providers
- **`codexbar cost`** — Local cost scanning for Codex + Claude
- **`codexbar config`** — Full config management CLI
- **`codexbar cards`** — Terminal card grid display
- **`codexbar diagnose`** — Provider diagnostics
- **`codexbar sessions`** — Live session listing

---

## 5. Provider Priority Ranking

### 5.1 Tier 1 — Essential (Must Implement First)

These are the most commonly used providers with clear API surfaces:

| Priority | Provider | Auth | Endpoint | Linux |
|---|---|---|---|---|
| 1 | **OpenAI** | Admin API key | `api.openai.com/v1/organizations/*` | `full` |
| 2 | **Claude** | Admin API key | `api.anthropic.com/v1/organizations/*` | `full` |
| 3 | **Gemini** | OAuth via CLI | Gemini CLI credentials | `partial` |
| 4 | **OpenRouter** | API key | openrouter.ai API | `full` |
| 5 | **GroqCloud** | API key | Groq Prometheus metrics | `full` |

### 5.2 Tier 2 — High Value (Should Implement Second)

| Priority | Provider | Auth | Endpoint | Linux |
|---|---|---|---|---|
| 6 | **ElevenLabs** | API key | `api.elevenlabs.io/v1/user/subscription` | `full` |
| 7 | **DeepSeek** | API key | `platform.deepseek.com/v1/users/me/balance` | `full` |
| 8 | **Moonshot** | API key | `api.moonshot.ai/v1/users/me/balance` | `full` |
| 9 | **z.ai** | API key | z.ai quota API | `full` |
| 10 | **Copilot** | Device flow / token | `api.github.com/copilot_internal/user` | `full` |
| 11 | **Warp** | API key | Warp GraphQL API | `full` |
| 12 | **AWS Bedrock** | AWS credentials | AWS Cost Explorer | `full` |
| 13 | **LLM Proxy** | API key + URL | Custom `/v1/quota-stats` | `full` |
| 14 | **LiteLLM** | API key + URL | Custom `/key/info`, `/user/info` | `full` |
| 15 | **ClawRouter** | API key + URL | Custom `/v1/usage` | `full` |

### 5.3 Tier 3 — Medium Value (Implement Third)

| Priority | Provider | Auth | Endpoint | Linux |
|---|---|---|---|---|
| 16 | **Codex** | CLI RPC / OAuth | `codex app-server` JSON-RPC | `full` |
| 17 | **Cursor** | Browser cookies | Internal API | `partial` |
| 18 | **Windsurf** | Browser cookies / SQLite | Internal API | `partial` |
| 19 | **Azure OpenAI** | API key + endpoint | Azure chat-completions | `full` |
| 20 | **Deepgram** | API key | Deepgram usage API | `full` |
| 21 | **Manus** | Session token | `api.manus.im` | `partial` |
| 22 | **OpenRouter** | API key | OpenRouter API | `full` |
| 23 | **Chutes** | API key | `api.chutes.ai` | `full` |
| 24 | **Poe** | API key | Poe usage API | `full` |
| 25 | **Codebuff** | API key | Codebuff API | `full` |
| 26 | **Venice** | API key | Venice DIEM/USD API | `full` |
| 27 | **Kimi** | API key | Kimi Code API | `full` |
| 28 | **MiniMax** | API key | MiniMax coding plan API | `full` |
| 29 | **Grok** | CLI / browser cookies | `grok agent stdio` / grok.com | `partial` |
| 30 | **Vertex AI** | gcloud OAuth | Cloud Monitoring | `partial` |

### 5.4 Tier 4 — Lower Priority (Nice to Have)

| Priority | Provider | Auth | Endpoint | Linux |
|---|---|---|---|---|
| 31 | **JetBrains AI** | Local XML file | `AIAssistantQuotaManager2.xml` | `full` |
| 32 | **Kiro** | CLI subprocess | `kiro-cli chat /usage` | `full` |
| 33 | **Amp** | Local CLI / API | `amp usage` | `full` |
| 34 | **Ollama** | API key / cookies | Ollama Cloud API | `partial` |
| 35 | **Antigravity** | Local LSP | Localhost HTTPS | `full` |
| 36-57 | Others | Various | Various | Mixed |

---

## 6. Core Implementation Patterns

### 6.1 API-Key Provider Pattern (Most Common)

```python
# Pattern: Resolve token from config/env → HTTP GET → Parse JSON → RateWindow

class APIKeyProvider:
    def __init__(self, id, api_key, base_url=None):
        self.api_key = api_key  # from config or env
        self.base_url = base_url or DEFAULT_URL

    async def fetch(self):
        headers = {"Authorization": f"Bearer {self.api_key}"}
        response = await self.http.get(self.endpoint, headers=headers)
        return self.parse(response.json())

    def parse(self, data):
        return UsageSnapshot(
            primary=RateWindow(
                used_percent=data["used_percent"],
                resets_at=data["resets_at"],
            ),
            identity=ProviderIdentity(
                account_email=data.get("email"),
            )
        )
```

### 6.2 OAuth Device Flow Pattern (Copilot, Codex)

```python
class OAuthDeviceFlow:
    DEVICE_CLIENT_ID = "..."
    DEVICE_SCOPE = "read:user"

    async def initiate(self):
        # POST /login/device/code → device_code, user_code, verification_uri
        resp = await self.http.post(self.device_url, data={
            "client_id": self.CLIENT_ID,
            "scope": self.SCOPE,
        })
        return DeviceCodeResponse(**resp.json())

    async def poll(self, device_code):
        # Poll /login/oauth/access_token until approved
        while True:
            resp = await self.http.post(self.token_url, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": self.CLIENT_ID,
            })
            if resp.status == 200:
                return AccessTokenResponse(**resp.json())
            elif resp.status == 400 and resp.json().get("error") == "authorization_pending":
                await asyncio.sleep(resp.json().get("interval", 5))
            else:
                raise OAuthError("Device flow failed")
```

### 6.3 CLI Subprocess Pattern (Codex, Kiro, Amp)

```python
class CLIFetchStrategy:
    def __init__(self, binary_name, args):
        self.binary_name = binary_name
        self.args = args

    async def fetch(self):
        proc = await asyncio.create_subprocess_exec(
            self.binary_name, *self.args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=10.0
        )
        return self.parse(stdout.decode())
```

### 6.4 Browser Cookie Pattern (Cursor, Windsurf, etc.)

```python
class BrowserCookieStrategy:
    def __init__(self, domains, browser=None):
        self.domains = domains
        self.browser = browser  # Chrome, Firefox, Safari (macOS only)

    async def fetch_cookies(self):
        # Try SweetCookieKit / keychain-backed import (macOS)
        # Fall back to manual cookie header from config
        if self.browser and is_macos():
            return await self.import_browser_cookies()
        elif self.manual_cookie_header:
            return self.normalize_cookie_header(self.manual_cookie_header)
        return None

    async def fetch(self):
        cookies = await self.fetch_cookies()
        if not cookies:
            raise CookieError("No browser cookies available")
        return await self.query_provider(cookies)
```

### 6.5 Admin API Pattern (OpenAI, Claude)

```python
class AdminAPIProvider:
    def __init__(self, api_key, provider):
        self.api_key = api_key
        self.provider = provider  # "openai" or "claude"

    async def fetch(self):
        # Two parallel requests: cost report + messages usage
        cost_data = await self._fetch_cost_report()
        msg_data = await self._fetch_messages_usage()
        return self._merge(cost_data, msg_data)

    async def _fetch_cost_report(self):
        url = f"https://api.{self.provider}.com/v1/organizations/cost_report"
        params = {"starting_at": ..., "ending_at": ..., "bucket_width": "1d"}
        headers = self._auth_headers()
        return await self.http.get(url, params=params, headers=headers)

    def _auth_headers(self):
        if self.provider == "claude":
            return {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }
        else:
            return {"Authorization": f"Bearer {self.api_key}"}
```

### 6.6 Proxy/Aggregate Pattern (LLM Proxy, LiteLLM, ClawRouter)

```python
class ProxyProvider:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def fetch(self):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        # Provider-specific endpoint
        response = await self.http.get(f"{self.base_url}{self.endpoint}", headers=headers)
        return self.parse(response.json())
```

---

## 7. Host APIs (Shared Infrastructure)

### 7.1 Available Host APIs in CodexBar

| Host API | Purpose | Linux Replacement |
|---|---|---|
| `HTTPAPI` (ProviderHTTPClient) | URLSession wrapper with domain allowlist | `httpx` / `aiohttp` |
| `PTYAPI` (TTYCommandRunner) | Run CLI with timeouts, substring send | `asyncio.subprocess` |
| `SubprocessRunner` | Generic subprocess management | `asyncio.create_subprocess_exec` |
| `BrowserCookieAPI` | Import cookies by browser/domain | `SweetCookieKit` Linux port or manual |
| `KeychainAPI` | Read keychain items (macOS only) | Not available; use env vars |
| `WebViewScrapeAPI` | WKWebView JS evaluation (macOS only) | Use HTTP client + HTML parser |
| `StatusAPI` | Statuspage.io polling | `httpx` + JSON parsing |
| `LoggerAPI` | Structured logging with redaction | `structlog` + `logging` |

### 7.2 Domain Allowlist Pattern

CodexBar restricts HTTP requests to known domains:

```python
ALLOWED_HOSTS = {
    "api.openai.com",
    "api.anthropic.com",
    "api.github.com",
    "openrouter.ai",
    "api.elevenlabs.io",
    "api.deepseek.com",
    "api.moonshot.ai",
    "api.manus.im",
    "console.groq.com",
    "platform.stepfun.com",
    # ... 50+ domains total
}
```

---

## 8. CLI Architecture

### 8.1 Commands

```
codexbar usage [--provider <name>] [--source <mode>] [--verbose] [--format json]
codexbar cards [--provider <name>] [--format json]
codexbar cost [--provider <name>] [--verbose]
codexbar sessions [list|focus]
codexbar serve [--port 8080] [--refresh-interval 60] [--request-timeout 30]
codexbar config validate
codexbar config dump
codexbar config providers
codexbar config enable --provider <name>
codexbar config disable --provider <name>
codexbar config set-api-key --provider <name> [--stdin | --api-key <key>]
codexbar cache clear [--cost | --cookies | --all]
codexbar diagnose [--provider <name>] [--verbose]
```

### 8.2 `codexbar serve` — HTTP Server

Serves `/health`, `/usage`, `/cost` endpoints on localhost:

```
GET /health                     → {"status": "ok", "version": "..."}
GET /usage?provider=codex       → JSON array of usage snapshots
GET /cost?provider=claude       → JSON array of cost snapshots
```

This is the primary integration point for Linux desktop extensions (waybar, GNOME, KDE).

### 8.3 Config File Permissions

- File permissions set to `0600` (owner read/write only)
- Never committed to version control
- Secrets in config are API keys, cookies, and OAuth tokens

---

## 9. Python Port Recommendations

### 9.1 Recommended Architecture

```
codexbar-python/
├── codexbar/
│   ├── __init__.py
│   ├── providers/              # Provider implementations
│   │   ├── base.py            # Base provider class, RateWindow, UsageSnapshot
│   │   ├── openai.py
│   │   ├── claude.py
│   │   ├── gemini.py
│   │   ├── copilot.py
│   │   ├── deepseek.py
│   │   ├── moonshot.py
│   │   ├── openrouter.py
│   │   ├── groq.py
│   │   ├── elevenlabs.py
│   │   ├── warp.py
│   │   ├── bedrock.py
│   │   ├── litellm.py
│   │   ├── llm_proxy.py
│   │   ├── clawrouter.py
│   │   ├── deepgram.py
│   │   ├── azure_openai.py
│   │   ├── z_ai.py
│   │   ├── venice.py
│   │   ├── poe.py
│   │   ├── chutes.py
│   │   ├── codebuff.py
│   │   ├── crof.py
│   │   ├── kimi.py
│   │   ├── minimax.py
│   │   ├── kimi_k2.py
│   │   ├── kilo.py
│   │   ├── doubao.py
│   │   ├── synthetic.py
│   │   ├── crossmodel.py
│   │   ├── antigravity.py
│   │   ├── jetbrains.py
│   │   ├── kiro.py
│   │   ├── amp.py
│   │   ├── ollama.py
│   │   ├── browser/           # Browser cookie strategies
│   │   │   ├── base.py
│   │   │   ├── chrome.py
│   │   │   ├── firefox.py
│   │   │   └── manual.py
│   │   └── registry.py        # Provider registry + auto-discovery
│   ├── config/
│   │   ├── __init__.py
│   │   ├── loader.py          # Load config from XDG paths
│   │   ├── schema.py          # Config schema validation
│   │   └── store.py           # Config file write operations
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── usage.py           # `codexbar usage`
│   │   ├── cards.py           # `codexbar cards`
│   │   ├── cost.py            # `codexbar cost`
│   │   ├── serve.py           # `codexbar serve` HTTP server
│   │   ├── config_cmd.py      # `codexbar config *` commands
│   │   ├── sessions.py        # `codexbar sessions`
│   │   ├── diagnose.py        # `codexbar diagnose`
│   │   └── cache.py           # `codexbar cache clear`
│   ├── http/
│   │   ├── __init__.py
│   │   ├── client.py          # HTTP client with domain allowlist
│   │   └── rate_limiter.py    # Per-provider rate limiting
│   ├── oauth/
│   │   ├── __init__.py
│   │   ├── device_flow.py     # GitHub/OAuth device flow
│   │   └── token_store.py     # Token persistence
│   ├── subprocess/
│   │   ├── __init__.py
│   │   └── runner.py          # CLI subprocess management
│   └── utils/
│       ├── __init__.py
│       ├── crypto.py          # Hashing, signing
│       ├── datetime.py        # Timezone handling
│       └── logging.py         # Structured logging
├── tests/
│   ├── providers/
│   ├── config/
│   ├── cli/
│   └── fixtures/
├── pyproject.toml
└── README.md
```

### 9.2 Dependencies

```toml
[project]
dependencies = [
    "httpx>=0.27",           # Async HTTP client (replaces URLSession)
    "pydantic>=2.0",         # Data validation (replaces Swift codable)
    "structlog>=24.0",       # Structured logging (replaces CodexBarLog)
    "click>=8.0",            # CLI framework (replaces Commander)
    "aiofiles>=24.0",        # Async file I/O
    "cryptography>=43.0",    # Crypto operations
    "keyring>=25.0",         # Linux keyring access (partial Keychain replacement)
]

[project.optional-dependencies]
browser = [
    "sqlite3",               # For SweetCookieKit Linux port
]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx-mock>=0.3",
]
```

### 9.3 Implementation Strategy

1. **Phase 1 — Core Infrastructure** (1-2 weeks)
   - Config loader (XDG paths, JSON schema)
   - HTTP client with domain allowlist
   - RateWindow + UsageSnapshot data models
   - Provider registry

2. **Phase 2 — API-Key Providers** (2-3 weeks)
   - Implement Tier 1 providers (OpenAI, Claude, DeepSeek, Moonshot, OpenRouter, Groq)
   - Implement Tier 2 providers (ElevenLabs, Warp, Venice, Poe, Chutes)
   - Proxy providers (LLM Proxy, LiteLLM, ClawRouter)

3. **Phase 3 — Complex Auth Providers** (2-3 weeks)
   - OAuth device flow (Copilot)
   - CLI subprocess (Codex, Kiro, Amp)
   - Browser cookie strategies (with manual fallback)

4. **Phase 4 — CLI + Serve** (1-2 weeks)
   - `codexbar usage` command
   - `codexbar serve` HTTP server
   - `codexbar config` management commands
   - Terminal rendering (cards, text)

5. **Phase 5 — Remaining Providers** (ongoing)
   - Browser cookie providers (partial)
   - Cloud providers (Vertex AI)
   - Regional providers (Alibaba, StepFun)

---

## 10. Key API Endpoints Summary

### 10.1 OpenAI

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/organization/cost_report` | GET | `Bearer <admin_key>` | Cost breakdown by description |
| `/v1/organization/usage_report/messages` | GET | `Bearer <admin_key>` | Message counts by model |
| `/v1/billing/credit_grants` | GET | `Bearer <key>` | Credit balance (legacy) |

### 10.2 Claude (Anthropic)

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/organizations/cost_report` | GET | `x-api-key` + `anthropic-version: 2023-06-01` | Cost by description |
| `/v1/organizations/usage_report/messages` | GET | Same | Message counts by model |

### 10.3 Copilot (GitHub)

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/login/device/code` | POST | Client ID | Initiate device flow |
| `/login/oauth/access_token` | POST | Client ID | Poll for token |
| `/copilot_internal/user` | GET | `token <oauth_token>` | Usage quotas |
| `/user` | GET | `token <oauth_token>` | GitHub identity |

### 10.4 DeepSeek

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/users/me/balance` | GET | `Bearer <key>` | Account balance |

### 10.5 Moonshot

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/users/me/balance` | GET | `Bearer <key>` | Account balance |

### 10.6 ElevenLabs

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/user/subscription` | GET | `xi-api-key` header | Subscription + character credits |

### 10.7 OpenRouter

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/v1/key` | GET | `Bearer <key>` | Credits + rate limits |

### 10.8 GroqCloud

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| Enterprise Prometheus metrics | GET | API key | Request/token/cache-hit rates |

### 10.9 LLM Proxy / LiteLLM / ClawRouter

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/quota-stats` | GET | `Bearer <key>` | LLM Proxy aggregate usage |
| `/key/info` | GET | `Bearer <key>` | LiteLLM key budget |
| `/user/info` | GET | `Bearer <key>` | LiteLLM user budget |
| `/team/info` | GET | `Bearer <key>` | LiteLLM team budget |
| `/v1/usage` | GET | `Bearer <key>` | ClawRouter monthly budget + spend |

### 10.10 AWS Bedrock

| Service | Method | Auth | Purpose |
|---|---|---|---|
| Cost Explorer | GET | AWS SigV4 | Bedrock spend |
| CloudWatch | GET | AWS SigV4 | Claude token/request totals |

### 10.11 Devin

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/<org-id>/billing/quota/usage` | GET | `Authorization: Bearer <token>` | Daily + weekly quota |

### 10.12 Manus

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/user.v1.UserService/GetAvailableCredits` | POST | `session_id` cookie | Credit balance |

### 10.13 T3 Chat

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/trpc/getCustomerData` | GET | Browser cookies | Customer data (Base + Overage buckets) |

---

## 11. Status Polling

Most providers have a status page URL for incident polling:

| Provider | Status URL |
|---|---|
| OpenAI / Codex | `https://status.openai.com` |
| Claude | `https://status.claude.com` |
| Copilot / GitHub | `https://www.githubstatus.com` |
| Cursor | `https://status.cursor.com` |
| GroqCloud | `https://status.groq.com` |
| ElevenLabs | `https://status.elevenlabs.io` |
| DeepSeek | `https://status.deepseek.com` |
| Mistral | `https://status.mistral.ai` |
| OpenRouter | `https://status.openrouter.ai` |
| Gemini | Google Workspace Apps Status |
| Azure OpenAI | Azure status (manual link) |
| AWS Bedrock | AWS Health Dashboard |
| x.ai / Grok | `https://status.x.ai` |

---

## 12. Token Resolution

CodexBar resolves tokens through a layered priority:

1. **Config file** (`~/.config/codexbar/config.json` → `providers[].apiKey`)
2. **Environment variables** (provider-specific, e.g. `OPENAI_ADMIN_KEY`)
3. **Default env vars** (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)
4. **Browser cookies** (for web-based providers)
5. **CLI credentials** (e.g. `~/.grok/auth.json`, `~/.codex/auth.json`)
6. **Keychain** (macOS only)
7. **Manual token accounts** (multi-account support)

---

## 13. Refresh Cadence

| Mode | Interval |
|---|---|
| Manual | On-demand |
| 1m | 1 minute |
| 2m | 2 minutes |
| 5m | 5 minutes (default) |
| 15m | 15 minutes |
| 30m | 30 minutes |
| Adaptive | 2-30 min based on interaction + power/thermal state |

---

## 14. Data Models

### 14.1 RateWindow

```python
@dataclass
class RateWindow:
    used_percent: float          # 0.0 to 1.0 (or >1.0 for over-quota)
    window_minutes: Optional[int]
    resets_at: Optional[datetime]
    reset_description: Optional[str]
```

### 14.2 UsageSnapshot

```python
@dataclass
class UsageSnapshot:
    primary: Optional[RateWindow]
    secondary: Optional[RateWindow]
    tertiary: Optional[RateWindow]
    extra_rate_windows: Optional[List[RateWindow]]
    provider_cost: Optional[CostSnapshot]
    updated_at: datetime
    identity: Optional[ProviderIdentitySnapshot]
    codex_reset_credits: Optional[List[ResetCredit]]
```

### 14.3 ProviderIdentitySnapshot

```python
@dataclass
class ProviderIdentitySnapshot:
    provider_id: UsageProvider
    account_email: Optional[str]
    account_organization: Optional[str]
    login_method: Optional[str]
```

### 14.4 CreditsSnapshot

```python
@dataclass
class CreditsSnapshot:
    remaining: float
    events: List[CreditsEvent]
    updated_at: datetime
    codex_credit_limit: Optional[CodexCreditLimit]
```

---

## 15. Observations for Python Port

### 15.1 What Translates Well to Python

- **API-key providers** (20+ providers) — straightforward HTTP + JSON
- **Proxy providers** (LLM Proxy, LiteLLM, ClawRouter) — generic pattern
- **Admin APIs** (OpenAI, Claude) — parallel HTTP requests + JSON parsing
- **CLI subprocess** (Codex, Kiro, Amp) — asyncio subprocess
- **Local file reads** (JetBrains AI XML, Windsurf SQLite) — standard libraries
- **Config management** — XDG paths + JSON schema
- **CLI commands** — click + rich for terminal rendering
- **HTTP serve** — aiohttp or httpx-starlette for local server

### 15.2 What Needs Special Handling

- **OAuth device flow** — needs browser URL display + polling
- **Browser cookie import** — Linux has no native equivalent; use manual paste or SweetCookieKit Linux port
- **Keychain** — use `keyring` Python package on Linux
- **PTY sessions** — use `asyncio.subprocess` with custom I/O handling
- **WebSocket/gRPC** (Grok billing) — may need `grpcio` or custom HTTP/2 client

### 15.3 What Is Not Feasible on Linux

- **WidgetKit widgets** — no equivalent on Linux; use `codexbar serve` + waybar/GNOME extensions
- **Keychain-backed browser import** — requires manual cookie paste on Linux
- **macOS-only status page polling** — some providers lack public status APIs

---

## 16. References

- **Architecture doc**: [docs/architecture.md](https://github.com/steipete/CodexBar/blob/main/docs/architecture.md)
- **Provider authoring**: [docs/provider.md](https://github.com/steipete/CodexBar/blob/main/docs/provider.md)
- **Provider catalog**: [docs/providers.md](https://github.com/steipete/CodexBar/blob/main/docs/providers.md)
- **Configuration**: [docs/configuration.md](https://github.com/steipete/CodexBar/blob/main/docs/configuration.md)
- **Refresh loop**: [docs/refresh-loop.md](https://github.com/steipete/CodexBar/blob/main/docs/refresh-loop.md)
- **CLI configuration**: [docs/cli-configuration.md](https://github.com/steipete/CodexBar/blob/main/docs/cli-configuration.md)
- **Individual provider docs**: [docs/](https://github.com/steipete/CodexBar/tree/main/docs)
- **Source code**: [Sources/CodexBarCore/Providers/](https://github.com/steipete/CodexBar/tree/main/Sources/CodexBarCore/Providers)
- **Package.swift**: [Package.swift](https://github.com/steipete/CodexBar/blob/main/Package.swift)
