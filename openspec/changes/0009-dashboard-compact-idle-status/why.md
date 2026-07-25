# Why: Surface Compact Idle Release In Control Center

Compact model 現在會在閒置五分鐘後自動釋放，但操作人員必須分別查看
Lemonade health、systemd 與 model manifest 才能知道 policy 是否運作。
Control Center 已聚合 loaded models，適合直接顯示這份狀態。

Dashboard 應顯示 timer 是否 active、`coder-compact` 是 unloaded、in use
或 idle，以及剩餘 idle 時間，但不新增具破壞性的 unload control。
