# AIPC 主要核心狀態（2026-07-10）

產品主線是 **always-on 閉環**（architecture §2.1）：

```text
hear → think → speak → remember → manage
SenseVoice → resident-small (/chat) → Kokoro → mem0 → portal
```

本文區分：**已站上閉環的核心**、**核心還缺的塊**、**週邊可延後**。

---

## 1. 已站上（可日常用）

| 塊 | 狀態 | 備註 |
|---|---|---|
| 系統底盤 (Phase 0 大部) | 已上線 | UMA / ROCm 路徑 / SOPS 機制 |
| LiteLLM + Lemonade + models | 已上線 | resident-small 常駐；agent/Hermes 為角色層 |
| 語音 batch 閉環 | **hardware 可用** | wake/PTT → once → STT → /chat → TTS + overlay |
| 本地 intents | 已上線 | 開面板 / 時間 / 音量 / mute 等 |
| mem0 服務 | 已上線 | recall/remember 掛在 orchestrator |
| portal 管理頁 | v0 可用 | `aipc portal` |
| agent-orchestrator `/chat` | 已上線 | Daily Assistant + Hermes 路由 |
| agent-gate | 已上線 | 權限閘門 |
| Dev 工具鏈大部 | 已上線 | Continue/Cline/Aider/Goose/OpenCode/CCS/CodexBar |
| Qwythos-9B | 角色層 | Hermes tool-call 層，非 baseline |

---

## 2. 主要核心還缺的塊（優先序）

### P0 — 閉環體感（使用者每天摸到）

| 缺口 | 為何是核心 | 狀態 2026-07-10 |
|---|---|---|
| **串流 turn（TTFA）** | batch 全程死寂；Siri 感靠「先出聲」 | **本夜已實作 static 層**（`/chat/stream` + `aipc-voice-stream`）；預設 `AIPC_VOICE_STREAM=0`，待 hardware 量 TTFA 後再開 |
| **中文 TTS 品質** | CosyVoice 仍 degraded；Kokoro 可聽但非 clone | live unit 在、模型就緒後切 |
| **長語音 / 連續聽寫** | Paraformer streaming 仍 `.disabled` | 非短指令必需 |
| **Secrets 實鑰** | cloud alias / 部分 tool 永遠 not_configured | 機器狀態常與設計不符（見 live-hotfix） |
| **VLM `vlm-qwen2vl`** | screen-control / Browser 視覺 | **2026-07-10 別名已接回** LiteLLM→Lemonade Gemma-4+mmproj（on-demand；live `/v1/models` 已見）；screen-control 仍 `.disabled`（kdotool/input）；完整 screenshot 推理解 hardware 再驗 |

### P1 — 記憶閉環（「記得」真的有料）

| 缺口 | 狀態 |
|---|---|
| **rag-ingest** 文件/瀏覽器/螢幕入庫 | `.disabled`，未 hardware-verify |
| **db-qdrant** | `.disabled`（embedder+postgres 已開） |
| mem0 與語音 episode 品質 | 服務在；推斷/去噪仍粗 |
| **OOM guard** | 模組已寫完 render-verified，仍 `.disabled` 待校準 |

沒有 ingest，RAG 等於空庫；閉環「remember」目前主要靠 mem0 短記憶。

### P2 — Agent 能力（「會做事」）

| 缺口 | 狀態 |
|---|---|
| Researcher / Coder / Browser 子圖 | phase-4 tasks 2.3–2.5 未做 |
| LangGraph checkpointer + `aipc agent resume` | 2.7 未做 |
| browser / code-shell / calendar / search / screen | 實作有、**仍 `.disabled`**（§9 要 hardware） |
| tavily 等 secret 抽取 | secrets-sops 缺口 |

Orchestrator 能聊 + Hermes 複雜任務；桌面工具面尚未全開。

### P3 — 可運維 / 可重裝

| 缺口 | 狀態 |
|---|---|
| **ops-doctor** | 模組在、`.disabled` |
| **ops-backup** | `.disabled` |
| Phase 7 firstboot 完整 wizard | 大量 open |
| 正式 bootc 映像重建 | live-hotfix 堆積；重啟清 ostree unlock 另見 checklist |

### P4 — 非主線（可睡）

- Phase 5 Gaming 全 `.disabled`、tasks 0 done
- Windows-direct / oneclick installer
- ChatGPT online 已大部分做完但非 local-first 主線
- Cloud LLM fallback change 未實作

---

## 3. 本夜一整撥（voice-streaming-turn）

**做了什麼（repo，static / self-test）：**

1. `agent-orchestrator`：`POST /chat/stream` SSE（token / done / error / session_id）
2. `aipc-voice-stream`：STT → stream → 句切 TTS 佇列 → 失敗回落 `aipc-voice-once`
3. wake：`AIPC_VOICE_STREAM=1` 時走 stream worker（預設 0）
4. `aipc voice status` 顯示 voice-stream 旗標與 helper
5. pytest / module verify 覆蓋 self-test

**刻意沒做：**

- 未預設開啟 stream（要 hardware TTFA + barge-in）
- 未 touch ostree re-layer / reboot
- 未 enable 任何 `.disabled` 模組

**醒來後 hardware 驗收（可選）：**

```bash
# 1) 熱補 orchestrator stream 路由（若仍走 live /var/lib 路徑）
# 2) 熱補 aipc-voice-stream 到 ~/.local/bin 或 /var/lib
export AIPC_VOICE_STREAM=1
aipc-voice-stream --wav /path/to/cmd.wav --session-id voice-test
# 或重啟 wake 並設 Environment=AIPC_VOICE_STREAM=1
aipc voice status   # 應見 voice-stream 行
```

---

## 4. 建議下一整撥（睡醒選）

1. **Hardware：開 stream 量 TTFA** → 綠了再考慮預設 1
2. **OOM guard 校準後 enable**（128GB 上多模型安全網）
3. **rag-ingest 最小路徑**：Desktop + Documents → embedder → postgres（先不開 qdrant）
4. **ops-doctor enable** + 閉環 probes
5. phase-4：checkpointer 或 Researcher 二選一

Gaming / installer / cloud fallback 不擋主線閉環。
