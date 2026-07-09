# Voice runtime flow (locked-in 2026-07-10)

## Happy path

```
PTT (控制中心 / aipc voice ptt)  ──┐
                                    ├→ state=wake/recording → overlay 右上角
「嘿助理」能量+STT 命中 ──────────┘         duck 媒體音
                                    → 同 mic 串流錄指令 (VAD 說完即停)
                                    → state=thinking
                                    → aipc-voice-once --wav (無第二 mic)
                                    → state=speaking → TTS 全音量播預設+藍牙
                                    → state=done → 還原音量 → listening
```

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
