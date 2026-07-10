# Voice runtime flow (locked-in 2026-07-10)

## Happy path

```
PTT (控制中心 / aipc voice ptt)  ──┐
                                    ├→ state=wake/recording → overlay 右上角
「嘿助理」能量+STT 命中 ──────────┘         duck 媒體音（只 duck 其他 stream）
                                    → 同 mic 串流錄指令 (VAD 說完即停)
                                    → state=thinking
                                    → aipc-voice-once --wav (無第二 mic)
                                         ├ local intents (快路徑，無 LLM)
                                         ├ Daily Assistant 工具路由（日程/郵件/文件/搜索/用量）
                                         └ 否則 /chat 閒聊
                                    → state=speaking → TTS
                                    → state=done → **followup（約 12s 可接話，無需喚醒詞）**
                                    → 逾時才 listening
```

## Local voice intents (`aipc_lib.voice_intents`)

| 說法示例 | 動作 |
|----------|------|
| 打开面板 / open portal | 開 AIPC portal |
| 现在几点 / 今天几号 | 報時 / 日期 |
| 打开浏览器 / 打开终端 | 啟動 Zen/瀏覽器、Konsole |
| 静音助手 / 取消静音 | 用戶標記 + mute target |
| 调大/调小音量 | **僅當用戶明說** 才動 master ±10% |
| 语音状态 / 你能做什么 | 健康摘要 / 能力列表 |

## What must NOT happen

| Bug | Fix |
|-----|-----|
| Overlay 環境音亂跳 | 只 show: wake/recording/thinking/speaking/error/no_speech |
| Overlay 在正中 | `QT_QPA_PLATFORM=xcb` + setGeometry 右上角 |
| TTS 有聲但怪/聽不到 | 播報前還原音量；paplay 多 sink（BT+喇叭）；不把 duck 底當基準 |
| 音量卡 8–12% | `_user_volume_pct` sticky；還原永不 <20% |
| 「你好」誤喚醒 | phrase fuzzy 加長度約束；禁止裸 你好 |
| STT/TTS 搶 mic | 單 arecord；once 只吃 --wav |

## Knobs (wake unit env)

- `AIPC_WAKE_DENOISE=0` — 喚醒用原始麦
- `AIPC_WAKE_STT_LANG=zh`
- `AIPC_VOICE_DUCK_FACTOR=0.35`
- `AIPC_TTS_MIN_VOLUME=45`
- `AIPC_VOICE_UX_NOTIFY=auto` — overlay 在時不炸系統通知
- `AIPC_VOICE_STREAM=0` — **預設 batch** `aipc-voice-once`；設 `1` 且 `aipc-voice-stream` 存在時走串流 turn（`POST /chat/stream` → 句切 TTS）。失敗自動 `stream_fallback` → once。見 `openspec/changes/voice-streaming-turn/` 與 `docs/core-status.md`。
- `AIPC_VOICE_CHAT_STREAM_URL` — 預設 `http://127.0.0.1:4100/chat/stream`
- `AIPC_STREAM_TTS_MIN_CHARS` / `AIPC_STREAM_TTS_MAX_CHARS` — 句切閾值（預設 12 / 64）

## Streaming path (optional, default off)

```
wake EOS → aipc-voice-stream --wav
  → SenseVoice final STT
  → local intents (same as once)
  → SSE POST :4100/chat/stream  (token…)
  → sentence buffer → Kokoro chunk queue → paplay
  → on error: stream_fallback → aipc-voice-once --wav
```

SSE events: `session_id` | `token` | `done` | `error`（JSON in `data:` lines）。

## Services

- system: `aipc-voice-wake`, `aipc-voice-stt-sensevoice`, kokoro :8880
- user: `aipc-voice-overlay` (xcb)

## Verify

```bash
aipc voice status
aipc voice ptt          # 應 recording + 右上角
# 然後說話；結束後音量應回原值
pactl get-sink-volume @DEFAULT_SINK@
```
