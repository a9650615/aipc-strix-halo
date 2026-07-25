# CodexBar GUI 啟動指南

## 快速啟動

### 方法 1：使用啟動腳本（推薦）

```bash
# 在 bootc 鏡像中
/usr/lib/codexbar-gui/start.sh

# 或在開發環境
cd /var/home/birdyo/aipc-strix-halo/modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui
export PYTHONPATH="/usr/lib/codexbar-gui:${PYTHONPATH:-}"
python3 -m codexbar_gui
```

### 方法 2：通過桌面入口

1. 安裝 autostart entry：
```bash
sudo cp /usr/lib/codexbar-gui/autostart/codexbar-gui.desktop ~/.config/autostart/
```

2. 登出後重新登入，或手動啟動：
```bash
codexbar-gui
```

## 依賴要求

### 系統依賴（Bazzite/BootC）

```bash
# 安裝 libGL（PySide6 需要）
sudo rpm-ostree install libglvnd-glx

# 重啟以啟用
sudo systemctl reboot
```

### Python 依賴

```bash
# 安裝 PySide6
pip install PySide6>=6.6
```

## 啟動流程

1. **常駐 usage web**（`codexbar-gui-web.service`，user unit）
   - 埠：**8080**（HTML + `/usage` + `/health`，取代舊 `aipc-usage`）
   - 健康檢查：`http://127.0.0.1:8080/health`
   - Hermes：`CODEXBAR_USAGE_BASE=http://127.0.0.1:8080`

2. **創建系統托盤圖標**
   - 動態進度條圖標
   - 顏色根據使用量變化

3. **定期刷新數據**
   - 默認間隔：60 秒
   - 優先讀官方 `codexbar usage` / 本機 web

## 托盤定位（相容層）

`shell_adapter` 只換「怎麼掛」，UI 仍是同一套 `UsagePopover`。

| 環境變數 | 作用 |
|----------|------|
| （預設） | `window` — 自由視窗，**左鍵一定打得開**；假座標時貼該螢幕右上 |
| `CODEXBAR_TRAY_SHELL=sni_menu` | 右鍵小選單 + 左鍵仍走 window（完整 UI 不能塞 QMenu.popup） |

```bash
# 預設即可
flatpak run io.aipc.CodexBarGui
```

> Wayland 上完整 UI 用 `QMenu.popup` 會失敗（`Failed to create grabbing popup`），
> 所以預設不再走那條路。

## 故障排除

### libGL 錯誤

```
ImportError: libGL.so.1: cannot open shared object file
```

**解決方案**：
```bash
sudo rpm-ostree install libglvnd-glx
sudo systemctl reboot
```

### HTTP server 未啟動

```
Connection refused
```

**解決方案**：
```bash
# 正式：user unit（映像已 default.target.wants 啟用）
systemctl --user enable --now codexbar-gui-web.service

# 或手動 web-only
python3 -m codexbar_gui --web-only --web-port 8080

# 不要再用 aipc-usage serve（legacy stub，不會綁 :8080）
```

### 圖標不顯示

1. 檢查是否在有系統托盤的桌面環境
2. KDE Plasma：預設支援
3. GNOME：可能需要 `gnome-shell-extension-appindicator`

## 測試

```bash
# 測試 GUI 邏輯（無需圖形環境）
python3 /usr/lib/codexbar-gui/tests/test_gui_logic.py

# 測試 CLI
aipc-usage usage -f table
```

## 配置

配置文件：`~/.config/codexbar/config.json`

```json
{
  "version": 1,
  "providers": [
    {
      "id": "claude",
      "enabled": true,
      "apiKey": "sk-ant-..."
    }
  ]
}
```

## 日誌

```bash
# 啟用調試日誌
export CODAXBAR_GUI_LOG_LEVEL=DEBUG
codexbar-gui
```
