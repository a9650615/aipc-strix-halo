# CodexBar Usage Integration

## Why

CodexBar 是一個 macOS 選單列應用，提供 57+ 個 AI 編程工具的使用量統計。我們需要將它的核心 CLI 功能移植到 aipc tools 中，讓 Linux 用戶也能追蹤各種 AI 工具的使用情況。

## What

- 移植 CodexBar CLI 的核心 provider fetcher 邏輯到 Python
- 支援主要 provider：Codex, Claude, OpenAI, Copilot, Gemini, Cursor, OpenRouter, LiteLLM, Grok, DeepSeek 等
- 在 aipc tools 中新增 `aipc-usage` 命令
- 提供終端卡片顯示和 JSON 輸出格式

## How

1. 分析 CodexBar Swift 源碼，提取 provider 解析邏輯
2. 在 modules/dev-ai-codexbar-usage 中實作 Python 版本
3. 整合為 aipc tools venv 內的 `aipc-usage` CLI 工具
4. 支援環境變數和 config 文件配置

## Verification

- [ ] 靜態檢查通過 (ruff, mypy)
- [ ] render 檢查通過
- [ ] 核心 provider 解析器測試通過
