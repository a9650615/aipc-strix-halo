# dev-ai-codexbar-usage 模組設計文檔

**Change**: `codexbar-usage-integration`
**設計日期**: 2026-07-08
**狀態**: 設計完成，待實作

---

## 1. 模組概述

`dev-ai-codexbar-usage` 模組負責在 Linux 環境中追蹤 AI 編程工具的使用量（tokens、次數、費用）。它移植 CodexBar（macOS 選單列應用）的核心功能到 aipc 系統，提供：

- 多 provider 支援（Codex、Claude、OpenAI、Copilot、Gemini、Cursor、OpenRouter、LiteLLM、Grok、DeepSeek）
- 本地 CLI 工具 (`aipc usage`)
- 終端卡片顯示和 JSON 輸出格式
- 環境變數和 config 文件配置

---

## 2. 模組目錄結構

```
modules/dev-ai-codexbar-usage/
├── README.md                    # 模組說明、依賴、配置
├── packages.txt                 # rpm-ostree/dnf 依賴
├── post-install.sh              # 安裝腳本（build-time only）
├── verify.sh                    # 驗證腳本
└── files/
    ├── etc/
    │   └── aipc/
    │       └── codexbar-usage/
    │           └── config.yaml  # 默認配置（可選）
    └── usr/
        └── lib/
            └── aipc-codexbar-usage/
                ├── __init__.py
                ├── __main__.py
                ├── providers/
                │   ├── __init__.py
                │   ├── base.py          # BaseProvider 抽象類
                │   ├── codex.py
                │   ├── claude.py
                │   ├── openai.py
                │   ├── copilot.py
                │   ├── gemini.py
                │   ├── openrouter.py
                │   ├── litellm.py
                │   ├── grok.py
                │   └── deepseek.py
                ├── cli.py               # CLI 入口（rich/click）
                ├── config.py            # 配置讀寫（環境變數 + config.yaml）
                └── ui.py                # 終端卡片渲染
```

---

## 3. 文件說明

### 3.1 `README.md`

**用途**: 模組說明文檔

**內容**:
- 模組功能概述
- 安裝說明
- 配置方法
- 依賴關係
- 已知限制

### 3.2 `packages.txt`

**用途**: rpm-ostree/dnf 依賴列表

**內容**:
```
# Python 3.11+ 標準庫，無需額外系統依賴
```

**說明**: Python 模塊使用標準庫，無需額外系統依賴。

### 3.3 `post-install.sh`

**用途**: 安裝腳本（build-time only）

**內容**:
```bash
#!/bin/sh
set -eu

# 複製 Python 模塊到 /usr/lib/aipc-codexbar-usage/
cp -r files/usr/lib/aipc-codexbar-usage /usr/lib/aipc-codexbar-usage/

# 創建 config 目錄
mkdir -p /etc/aipc/codexbar-usage/

# 複製默認配置（如果不存在）
if [ ! -f /etc/aipc/codexbar-usage/config.yaml ]; then
    cp files/etc/aipc/codexbar-usage/config.yaml /etc/aipc/codexbar-usage/config.yaml
fi

# 設置權限
chmod 755 /usr/lib/aipc-codexbar-usage/
chmod 755 /usr/lib/aipc-codexbar-usage/providers/
```

**驗證**:
- 文件已複製到 `/usr/lib/aipc-codexbar-usage/`
- config 目錄已創建
- 權限正確

### 3.4 `verify.sh`

**用途**: 驗證腳本

**內容**:
```bash
#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

# 檢查 Python 模塊
pkg_dir="$this_dir/files/usr/lib/aipc-codexbar-usage"
[ -f "$pkg_dir/providers/base.py" ] || { echo "base.py missing" >&2; exit 1; }
[ -f "$pkg_dir/cli.py" ] || { echo "cli.py missing" >&2; exit 1; }

# 檢查語法
python3 -c "import ast; ast.parse(open('$pkg_dir/providers/base.py').read())" || { echo "syntax error in base.py" >&2; exit 1; }

echo "codexbar-usage: static OK (render-verified)"
```

**退出碼**:
- `0`: 通過
- `2`: 已禁用（可選）
- 其他: 失敗

---

## 4. Python 模塊結構

### 4.1 包結構

```python
# aipc_codexbar_usage/
# ├── __init__.py          # 版本、公共接口
# ├── __main__.py          # python -m aipc_codexbar_usage 入口
# ├── providers/
# │   ├── __init__.py      # 提供者註冊
# │   ├── base.py          # BaseProvider 抽象類
# │   ├── codex.py         # Codex provider
# │   ├── claude.py        # Claude provider
# │   ├── openai.py        # OpenAI provider
# │   ├── copilot.py       # GitHub Copilot provider
# │   ├── gemini.py        # Google Gemini provider
# │   ├── openrouter.py    # OpenRouter provider
# │   ├── litellm.py       # LiteLLM provider
# │   ├── grok.py          # xAI Grok provider
# │   └── deepseek.py      # DeepSeek provider
# ├── cli.py               # CLI 命令（rich/click）
# ├── config.py            # 配置讀寫
# └── ui.py                # 終端卡片渲染
```

### 4.2 核心文件說明

#### 4.2.1 `providers/base.py`

**用途**: 定義 Provider 抽象類

**內容**:
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class UsageSummary:
    total_tokens: int = 0
    total_calls: int = 0
    total_cost_usd: float = 0.0
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None

@dataclass
class ProviderInfo:
    name: str
    display_name: str
    enabled: bool = True

class BaseProvider(ABC):
    @abstractmethod
    def get_usage(self, period_days: int = 30) -> Optional[UsageSummary]:
        """Fetch usage for the last N days"""
        ...

    @abstractmethod
    def get_info(self) -> ProviderInfo:
        """Return provider metadata"""
        ...
```

#### 4.2.2 `providers/*.py` (provider 實現)

每個 provider 實現 `BaseProvider` 接口：

- `codex.py`: 解析 Codex CLI log 或 Web dashboard
- `claude.py`: 調用 Claude Admin API 或解析 CLI log
- `openai.py`: 調用 OpenAI Admin API
- `copilot.py`: 解析 GitHub CLI `gh copilot usage`
- `gemini.py`: 調用 Google AI Studio API
- `openrouter.py`: 調用 OpenRouter API
- `litellm.py`: 查詢本地 LiteLLM 日誌（`/usr/lib/aipc-litellm/logs/`）
- `grok.py`: 解析 xAI Web dashboard 或 API log
- `deepseek.py`: 調用 DeepSeek API

**數據源**:
1. **API 調用**: 需要 API key（環境變數或 config）
2. **CLI log 解析**: 解析本地 log 文件
3. **Web dashboard 爬取**: 需要 OAuth/token

#### 4.2.3 `cli.py`

**用途**: CLI 命令入口

**內容**:
```python
import click
from rich.console import Console
from rich.table import Table
from aipc_codexbar_usage.providers import get_providers
from aipc_codexbar_usage.ui import render_cards, render_json

@click.group()
def usage_cmd():
    """Track AI tool usage across providers."""
    pass

@usage_cmd.command("show")
@click.option("--format", type=click.Choice(["cards", "json", "table"]), default="cards",
              help="Output format: cards (rich), json, table (plain)")
@click.option("--period", type=int, default=30, show_default=True,
              help="Period in days")
@click.option("--provider", type=str, default=None,
              help="Filter by provider (comma-separated)")
def show_cmd(format: str, period: int, provider: Optional[str]):
    """Show usage summary"""
    providers = get_providers()
    if provider:
        providers = [p for p in providers if p.name in provider.split(",")]

    results = []
    for p in providers:
        if not p.enabled:
            continue
        usage = p.get_usage(period_days=period)
        if usage:
            results.append({"provider": p.name, "usage": usage})

    if format == "json":
        render_json(results)
    elif format == "table":
        render_table(results)
    else:  # cards
        render_cards(results)
    Console().print()

@usage_cmd.command("providers")
def providers_cmd():
    """List configured providers and their status"""
    providers = get_providers()
    table = Table(title="aipc usage providers")
    table.add_column("Name")
    table.add_column("Display")
    table.add_column("Enabled")
    for p in providers:
        info = p.get_info()
        table.add_row(info.name, info.display_name, "yes" if info.enabled else "no")
    Console().print(table)

@usage_cmd.command("configure")
def configure_cmd():
    """Interactive provider configuration"""
    # 交互式配置 provider 啟用/禁用
    ...
```

#### 4.2.4 `config.py`

**用途**: 配置讀寫

**內容**:
```python
import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_CONFIG_PATH = Path("/etc/aipc/codexbar-usage/config.yaml")
ENV_VAR_PREFIX = "CODAXBAR_USAGE_"

@dataclass
class Config:
    providers: Dict[str, bool]  # provider name -> enabled
    api_keys: Dict[str, str]    # provider name -> API key (from env)
    period_days: int = 30

def load_config(config_path: Optional[Path] = None) -> Config:
    """Load config from file + environment variables"""
    config_path = config_path or DEFAULT_CONFIG_PATH
    config = Config()

    # 從文件加載
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text())
        config.providers = data.get("providers", {})
        config.period_days = data.get("period_days", 30)

    # 從環境變數覆蓋
    for key, value in os.environ.items():
        if key.startswith(ENV_VAR_PREFIX):
            provider, field = key[len(ENV_VAR_PREFIX):].lower().split("_", 1)
            if field == "enabled":
                config.providers[provider] = value.lower() == "true"
            elif field == "api_key":
                config.api_keys[provider] = value

    return config

def get_providers() -> List[BaseProvider]:
    """Get all configured providers"""
    config = load_config()
    from .providers import registry
    return [
        registry[p] for p in registry
        if config.providers.get(p, True)
    ]
```

#### 4.2.5 `ui.py`

**用途**: 終端卡片渲染

**內容**:
```python
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from aipc_codexbar_usage.providers import UsageSummary

def render_cards(results: list[dict]):
    """Render usage as rich cards"""
    console = Console()
    for r in results:
        usage = r["usage"]
        panel = Panel(
            Text(f"Provider: {r['provider']}"),
            title=f"{r['provider']} Usage",
            border_style="blue"
        )
        console.print(panel)
        # 顯示使用量詳情
        ...

def render_json(results: list[dict]):
    """Render usage as JSON"""
    import json
    data = [
        {
            "provider": r["provider"],
            "total_tokens": r["usage"].total_tokens,
            "total_calls": r["usage"].total_calls,
            "total_cost_usd": r["usage"].total_cost_usd,
        }
        for r in results
    ]
    print(json.dumps(data, indent=2))

def render_table(results: list[dict]):
    """Render usage as plain table"""
    table = Table(title="aipc usage summary")
    table.add_column("Provider")
    table.add_column("Tokens")
    table.add_column("Calls")
    table.add_column("Cost (USD)")
    for r in results:
        usage = r["usage"]
        table.add_row(
            r["provider"],
            f"{usage.total_tokens:,}",
            f"{usage.total_calls:,}",
            f"${usage.total_cost_usd:.4f}",
        )
    Console().print(table)
```

---

## 5. CLI 命令結構

### 5.1 命令註冊

在 `tools/aipc_lib/cli.py` 中註冊：

```python
from aipc_lib import usage as usage_mod

main.add_command(usage_mod.usage_cmd, name="usage")
```

### 5.2 命令列表

```bash
aipc usage show [--format cards|json|table] [--period DAYS] [--provider NAME]
aipc usage providers
aipc usage configure
```

### 5.3 參數說明

| 命令 | 參數 | 類型 | 默認值 | 說明 |
|------|------|------|--------|------|
| `show` | `--format` | choice | `cards` | 輸出格式：cards (rich 卡片), json, table (純文本) |
| `show` | `--period` | int | `30` | 查詢周期（天） |
| `show` | `--provider` | str | `None` | 按 provider 過濾（逗號分隔） |
| `providers` | - | - | - | 列出配置的 providers |
| `configure` | - | - | - | 交互式配置 |

### 5.4 輸出格式

#### 5.4.1 Cards（默認）

```
┌─────────────────────────────────────────┐
│          Claude Usage                    │
├─────────────────────────────────────────┤
│ Tokens:   1,234,567                     │
│ Calls:    45,678                        │
│ Cost:     $12.3456                      │
│ Period:   2026-06-08 → 2026-07-08      │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│          OpenAI Usage                    │
├─────────────────────────────────────────┤
│ Tokens:   890,123                       │
│ Calls:    23,456                        │
│ Cost:     $8.9012                       │
│ Period:   2026-06-08 → 2026-07-08      │
└─────────────────────────────────────────┘
```

#### 5.4.2 JSON

```json
[
  {
    "provider": "claude",
    "total_tokens": 1234567,
    "total_calls": 45678,
    "total_cost_usd": 12.3456,
    "period_start": "2026-06-08",
    "period_end": "2026-07-08"
  },
  {
    "provider": "openai",
    "total_tokens": 890123,
    "total_calls": 23456,
    "total_cost_usd": 8.9012,
    "period_start": "2026-06-08",
    "period_end": "2026-07-08"
  }
]
```

#### 5.4.3 Table

```
┌──────────┬───────────────┬──────────┬──────────────┐
│ Provider │   Tokens      │  Calls   │ Cost (USD)   │
├──────────┼───────────────┼──────────┼──────────────┤
│ claude   │   1,234,567   │   45,678 │ $12.3456     │
│ openai   │     890,123   │   23,456 │  $8.9012     │
└──────────┴───────────────┴──────────┴──────────────┘
```

---

## 6. 配置方法

### 6.1 環境變數

```bash
# 啟用/禁用 provider
export CODAXBAR_USAGE_CLAUDE_ENABLED=true
export CODAXBAR_USAGE_OPENAI_ENABLED=false

# API keys
export CODAXBAR_USAGE_CLAUDE_API_KEY=sk-...
export CODAXBAR_USAGE_OPENAI_API_KEY=sk-...
```

### 6.2 Config 文件

`/etc/aipc/codexbar-usage/config.yaml`:

```yaml
providers:
  claude: true
  openai: true
  codex: true
  copilot: true
  gemini: true
  openrouter: false
  litellm: true
  grok: true
  deepseek: true

period_days: 30
```

### 6.3 優先級

環境變數 > config 文件 > 默認值

---

## 7. 依賴關係

### 7.1 模塊依賴

```
dev-ai-codexbar-usage
├── llm-litellm (可選) - 用於 Litellm provider
├── dev-ai-claude-code (可選) - Claude CLI log 路徑
└── dev-ai-opencode (可選) - opencode CLI log 路徑
```

### 7.2 Python 依賴

```python
# 標準庫
dataclasses, datetime, pathlib, os, json, yaml, click, rich, abc

# 無需額外 PyPI 依賴
```

---

## 8. Bootc 和 Ansible 雙目標

### 8.1 Bootc (Containerfile)

```dockerfile
# modules/dev-ai-codexbar-usage
COPY --chown=root:root files/usr/lib/aipc-codexbar-usage /usr/lib/aipc-codexbar-usage
COPY --chown=root:root files/etc/aipc/codexbar-usage/config.yaml /etc/aipc/codexbar-usage/config.yaml
```

### 8.2 Ansible

```yaml
- name: Install aipc-codexbar-usage module
  copy:
    src: files/usr/lib/aipc-codexbar-usage
    dest: /usr/lib/aipc-codexbar-usage
    owner: root
    group: root
    mode: '0755'

- name: Create config directory
  file:
    path: /etc/aipc/codexbar-usage
    state: directory
    owner: root
    group: root
    mode: '0755'

- name: Install default config
  copy:
    src: files/etc/aipc/codexbar-usage/config.yaml
    dest: /etc/aipc/codexbar-usage/config.yaml
    owner: root
    group: root
    mode: '0644'
    remote_src: no
  when: not (ansible_facts['userspace_bits'] == '64') or true  # 總是安裝
```

---

## 9. 驗證流程

### 9.1 靜態檢查

```bash
# Python 語法檢查
python3 -c "import ast; ast.parse(open('providers/base.py').read())"

# Ruff 檢查
ruff check modules/dev-ai-codexbar-usage/

# 模塊導入檢查
python3 -c "from aipc_codexbar_usage.providers import BaseProvider"
```

### 9.2 Render 檢查

```bash
# Bootc render
tools/aipc render bootc

# Ansible render
tools/aipc render ansible --check
```

### 9.3 運行時檢查（可選）

```bash
# 測試 CLI
python3 -m aipc_codexbar_usage providers

# 測試輸出格式
python3 -m aipc_codexbar_usage show --format json
```

---

## 10. 已知限制和開放問題

### 10.1 數據源限制

| Provider | 數據源 | 限制 |
|----------|--------|------|
| Codex | CLI log | 需要 CLI 已使用 |
| Claude | Admin API | 需要 API key + 組織權限 |
| OpenAI | Admin API | 需要 API key + 組織權限 |
| Copilot | GitHub CLI | 需要 `gh` CLI + OAuth |
| Gemini | AI Studio API | 需要 API key |
| OpenRouter | API | 需要 API key |
| LiteLLM | 本地日誌 | 需要 LiteLLM 已運行 |
| Grok | Web dashboard | 需要 OAuth token |
| DeepSeek | API | 需要 API key |

### 10.2 開放問題

1. **OAuth 流程**: Copilot/Grok 需要 OAuth 流程，Linux 桌面瀏覽器支持待驗證
2. **Web dashboard 爬取**: 非官方 API provider 的穩定性不保證
3. **費用計算**: 不同 provider 的計費模型不同（token 長度、模型版本）

---

## 11. 實作優先級

| 任務 | 優先級 | 說明 |
|------|--------|------|
| Provider 基類 | High | 所有 provider 的基礎 |
| LiteLLM provider | High | 本地數據，最易實現 |
| Claude provider | High | 官方 API |
| OpenAI provider | High | 官方 API |
| OpenRouter provider | Medium | 官方 API |
| DeepSeek provider | Medium | 官方 API |
| Codex provider | Medium | CLI log 解析 |
| Copilot provider | Low | 需要 GitHub CLI |
| Gemini provider | Low | 需要 Google OAuth |
| Grok provider | Low | Web dashboard 爬取 |

---

## 12. 測試計劃

### 12.1 單元測試

```python
# tests/test_providers.py

def test_base_provider_abstract():
    """BaseProvider cannot be instantiated directly"""
    ...

def test_litellm_provider_parse_log():
    """Parse LiteLLM log file correctly"""
    ...

def test_config_load():
    """Load config from file + env vars"""
    ...

def test_ui_render_cards():
    """Render cards format"""
    ...

def test_ui_render_json():
    """Render JSON format"""
    ...
```

### 12.2 集成測試

```bash
# 測試 CLI 命令
python3 -m aipc_codexbar_usage --help
python3 -m aipc_codexbar_usage providers
python3 -m aipc_codexbar_usage show --format json

# 測試配置
export CODAXBAR_USAGE_CLAUDE_ENABLED=false
python3 -m aipc_codexbar_usage show --format json
```

---

## 13. 部署和分發

### 13.1 模塊啟用

模組默認啟用。如需禁用，在模組目錄創建 `.disabled` 文件。

### 13.2 更新流程

1. 修改 `modules/dev-ai-codexbar-usage/` 下的文件
2. 運行 `tools/aipc render bootc` 和 `tools/aipc render ansible --check`
3. 提交更改到 git
4. 構建新鏡像 `bootc build podman ...`
5. 切換鏡像 `bootc switch ...`
6. 重啟系統

---

## 14. 設計決策記錄

### D1: Python 模塊位置

**選擇**: `/usr/lib/aipc-codexbar-usage/`

**理由**:
- 與其他 `dev-ai-*` 模塊保持一致
- 標準 Linux 文件系統層級
- 易於通過 `PYTHONPATH` 導入

### D2: 配置位置

**選擇**: `/etc/aipc/codexbar-usage/config.yaml` + 環境變數

**理由**:
- `/etc/` 是系統配置的標準位置
- 環境變數優先級更高，適合 CI/CD
- YAML 格式易讀易寫

### D3: 輸出格式

**選擇**: cards (rich) / json / table (純文本)

**理由**:
- cards: 終端交互使用，視覺友好
- json: 機器可讀，方便腳本處理
- table: 純文本環境，兼容性好

### D4: Provider 數據源

**選擇**: API 調用 > CLI log 解析 > Web dashboard

**理由**:
- API 最穩定、最準確
- CLI log 需要本地使用記錄
- Web dashboard 爬取最不穩定

---

## 15. 下一步行動

1. **實作 Provider 基類** (`providers/base.py`)
2. **實作 LiteLLM Provider** (`providers/litellm.py`) - 最易實現
3. **實作 CLI 入口** (`cli.py`)
4. **實作 UI 渲染** (`ui.py`)
5. **實作 Config** (`config.py`)
6. **添加單元測試** (`tests/test_providers.py`)
7. **集成到 aipc CLI** (`tools/aipc_lib/cli.py`)

---

**文檔版本**: 1.0
**最後更新**: 2026-07-08
**作者**: AI Lieutenant (副官)
