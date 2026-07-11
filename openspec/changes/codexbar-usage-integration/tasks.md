# CodexBar Usage Integration - Tasks

## Task 1: Analyze CodexBar CLI Structure
**File**: `openspec/changes/codexbar-usage-integration/tasks.md`
**Status**: `completed`

- [x] 1.1 分析 CodexBar Package.swift 依賴和架構
- [x] 1.2 提取 provider 基類和核心 fetcher 模式
- [x] 1.3 識別需要支援的核心 provider（至少 10 個）
- [x] 1.4 文檔化 config 文件格式和 API 端點

**Files**: 只讀分析任務

**Verification**: 輸出分析報告到 `openspec/changes/codexbar-usage-integration/docs/architecture-analysis.md`

---

## Task 2: Design Python Module Structure
**File**: `openspec/changes/codexbar-usage-integration/tasks.md`
**Status**: `completed`

- [x] 2.1 設計 modules/dev-ai-codexbar-usage 結構
- [x] 2.2 定義 Python 模組的依賴和接口
- [x] 2.3 設計 CLI 命令結構 (`aipc-usage`)
- [x] 2.4 定義 output format (text/json/cards)

**Files**: 
- `openspec/changes/codexbar-usage-integration/specs/codexbar-usage.md`

**Verification**: 規格文檔通過 openspec validate

---

## Task 3: Implement Core Provider Parsers (Python)
**File**: `openspec/changes/codexbar-usage-integration/tasks.md`
**Status**: `completed`

- [x] 3.1 實作 provider 基類 `BaseProvider`
- [x] 3.2 實作 Codex provider (OAuth/CLI/Web)
- [x] 3.3 實作 Claude provider (Admin API/Web/CLI)
- [x] 3.4 實作 OpenAI provider (Admin API)
- [x] 3.5 實作 Copilot provider (Device Flow)
- [x] 3.6 實作 Gemini provider (OAuth API)
- [x] 3.7 實作 OpenRouter provider (API key)
- [x] 3.8 實作 LiteLLM provider (Proxy API)
- [x] 3.9 實作 Grok provider (CLI/Web)
- [x] 3.10 實作 DeepSeek provider (API key)

**Files**:
- `modules/dev-ai-codexbar-usage/src/providers/base.py`
- `modules/dev-ai-codexbar-usage/src/providers/codex.py`
- `modules/dev-ai-codexbar-usage/src/providers/claude.py`
- `modules/dev-ai-codexbar-usage/src/providers/openai.py`
- `modules/dev-ai-codexbar-usage/src/providers/copilot.py`
- `modules/dev-ai-codexbar-usage/src/providers/gemini.py`
- `modules/dev-ai-codexbar-usage/src/providers/openrouter.py`
- `modules/dev-ai-codexbar-usage/src/providers/litellm.py`
- `modules/dev-ai-codexbar-usage/src/providers/grok.py`
- `modules/dev-ai-codexbar-usage/src/providers/deepseek.py`

**Verification**: 
- `ruff check modules/dev-ai-codexbar-usage/`
- `mypy modules/dev-ai-codexbar-usage/`
- 單元測試通過

---

## Task 4: Implement CLI Interface and Terminal UI
**File**: `openspec/changes/codexbar-usage-integration/tasks.md`
**Status**: `completed`

- [x] 4.1 實現 CLI 入口 `aipc-usage`
- [x] 4.2 實現 config 文件讀寫
- [x] 4.3 實現終端卡片顯示 (rich/click)
- [x] 4.4 實現 JSON 輸出格式
- [x] 4.5 實現 provider 啟用/禁用配置

**Files**:
- `tools/aipc_lib/usage.py`
- `modules/dev-ai-codexbar-usage/src/cli.py`
- `modules/dev-ai-codexbar-usage/src/ui.py`

**Verification**:
- CLI 命令可執行
- JSON 輸出格式正確
- 終端卡片渲染正常

---

## Task 5: Integrate to aipc Tools
**File**: `openspec/changes/codexbar-usage-integration/tasks.md`
**Status**: `completed`

- [x] 5.1 在 module pyproject.toml 中添加依賴
- [x] 5.2 註冊 `aipc-usage` 命令
- [x] 5.3 添加模組到 bootc render
- [x] 5.4 添加模組到 ansible render
- [x] 5.5 更新 README

**Files**:
- `tools/pyproject.toml`
- `modules/dev-ai-codexbar-usage/files/usr/lib/aipc-codexbar-usage/pyproject.toml`
- `targets/bootc/Containerfile.generated`
- `targets/ansible/site.generated.yml`

**Verification**:
- `python -m aipc_lib.cli render bootc --image-ref localhost/aipc-strix-halo:dev --build-date 2026-07-09` 通過
- `python -m aipc_lib.cli render ansible` 通過
- `PYTHONPATH=modules/dev-ai-codexbar-usage/files/usr/lib/aipc-codexbar-usage python -m codexbar_usage --help` 顯示正確

---

## Task 6: Add Z.AI Subscription Quota Provider
**Status**: `pending`

- [ ] 6.1 Implement provider `zai` using CodexBar's Z.AI subscription usage source.
- [ ] 6.2 Normalize remaining quota and reset time through the existing
  `used_percent`, `resets_at`, and provider status schema.
- [ ] 6.3 Return a fail-soft status when credentials, quota, or upstream usage
  data are unavailable; routing must keep the request local.
- [ ] 6.4 Add one provider parser check and keep source/rendered package copies
  in sync.

---

## Summary

| Task | Status | Priority |
|------|--------|----------|
| 1. Architecture Analysis | completed | high |
| 2. Module Design | completed | high |
| 3. Core Provider Parsers | completed | high |
| 4. CLI Interface | completed | medium |
| 5. Integration | completed | high |
| 6. Z.AI Subscription Quota | pending | high |
