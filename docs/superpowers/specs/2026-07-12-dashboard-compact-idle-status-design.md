# Dashboard Compact Idle Status Design

## Goal

`coder-compact` 的自動釋放狀態顯示在既有 Control Center Runtime 卡片，回答三件事：

1. idle-release timer 是否 enabled/active。
2. compact 是 unloaded、in use 或 idle。
3. idle 時距離 release 還有多久。

## Scope

沿用 `/api/v1/dashboard` 與 Runtime 卡片。不新增 endpoint、journal
歷史、手動 unload、或通用 systemd 管理 UI。

## Data flow

`dashboard.py` 從 `/etc/aipc/models/models.yaml` 讀取
`coder-compact` 的 `model_id` 與 `idle_unload_after_s`，重用
`loaded_models()` 已取得的 Lemonade rows，並以 `systemctl is-enabled`
及 `systemctl is-active` 查 timer。

Backend 在 `runtime.compact_idle_release` 回傳 `model`、`state`、
`timer`、`timeout_s`、`idle_s`、`remaining_s`。`state` 僅為
`unloaded`、`in_use`、`idle` 或 `unknown`。`idle_s` 與
`remaining_s` 只在 loaded 且 idle 時出現。

Backend 用 `time.monotonic()` 解讀 Lemonade 的 monotonic-millisecond
`last_use`；browser 不處理 Lemonade 時鐘格式。

## Presentation

Runtime 卡保留既有 loaded-model summary，再加一行：

- `Compact unloaded · auto-release 5m · timer active`
- `Compact in use · timer active`
- `Compact idle 2m14s · release in 2m46s`

沿用 dashboard 每五秒 refresh，不新增 client timer。

## Failure handling

Manifest、Lemonade 或 systemd 任一來源失敗，只讓 compact 狀態顯示
`unknown`，不使整個 dashboard endpoint 失敗。Unloaded 是正常狀態。

## Verification

- Python assertions 覆蓋 unloaded、in-use、idle countdown 與 missing data。
- Frontend contract 覆蓋三種顯示文字。
- Portal static verification、OpenSpec strict、bootc 與 ansible render 通過。
- Live 驗證 dashboard endpoint 與 Runtime 卡，並確認沒有 unload 操作。
