# How: Derive Compact Residency State In The Dashboard Snapshot

在 `dashboard.py` 新增小型 helper，接受既有 loaded-model rows 與可注入的
test inputs。它讀取 `models.yaml` 的 compact policy、查 timer、以
`model_id` 配對 Lemonade health，並推導 state 與 countdown。

既有 `runtime` object 新增 `compact_idle_release`。Astro page 在 Runtime
card 格式化它，繼續沿用五秒 refresh。

任何來源失敗都降級為 `unknown`，不使 dashboard snapshot 失敗。
