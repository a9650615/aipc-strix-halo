# What: Add Compact Idle Status To The Runtime Card

擴充既有 dashboard snapshot，加入 derived compact idle-release status。
Backend 負責 manifest lookup、systemd checks 與 Lemonade monotonic-time
conversion；Runtime card 只格式化該物件。

## Capability Impact

- `aipc-portal`: dashboard 回報並顯示 compact idle-release status。
- `ai-runtime`: 不變；portal 只觀察 change 0006 已實作的 policy。

## Non-goals

- 不提供 manual unload button。
- 不新增 HTTP endpoint。
- 不顯示 model history 或 journal。
- 不建立 generalized systemd dashboard。
