#!/bin/bash
# Build and install CodexBar GUI as a user Flatpak (Applications menu).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_ID="io.aipc.CodexBarGui"
BRANCH="6.10"
BUILD_DIR="${ROOT}/.flatpak-build"
REPO_DIR="${ROOT}/.flatpak-repo"
STATE_DIR="${ROOT}/.flatpak-builder"

echo "==> Generating icon"
python3 <<'PY'
from pathlib import Path
try:
    from PySide6.QtGui import QImage, QPainter, QColor, QFont, Qt
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    img = QImage(128, 128, QImage.Format.Format_ARGB32)
    img.fill(QColor("#171a22"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#7aa2f7"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(16, 28, 96, 28, 10, 10)
    p.setBrush(QColor("#4ecdc4"))
    p.drawRoundedRect(16, 72, 64, 18, 8, 8)
    p.setPen(QColor("#e8ecf4"))
    f = QFont("Sans", 22, QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(img.rect().adjusted(0, -8, 0, 0), int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom), "CB")
    p.end()
    out = Path("io.aipc.CodexBarGui.png")
    img.save(str(out))
    print("wrote", out.resolve())
except Exception as e:
    # Fallback: minimal valid 1x1 expanded via convert if needed
    print("PySide icon failed:", e, file=__import__("sys").stderr)
    # Write a tiny PPM and hope; flatpak needs png
    import struct, zlib
    # solid blue 128x128 PNG minimal via pure python
    w = h = 128
    raw = b"".join(b"\x00" + bytes([0x17, 0x1a, 0x22]) * w for _ in range(h))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    Path("io.aipc.CodexBarGui.png").write_bytes(png)
    print("wrote fallback png")
PY

echo "==> Ensuring Flatpak runtimes (user)"
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo 2>/dev/null || true
flatpak install -y --user flathub \
  "org.kde.Platform//${BRANCH}" \
  "org.kde.Sdk//${BRANCH}" \
  "io.qt.PySide.BaseApp//${BRANCH}" || {
  echo "WARN: user install of runtime failed; trying system remotes" >&2
  flatpak install -y flathub \
    "org.kde.Platform//${BRANCH}" \
    "org.kde.Sdk//${BRANCH}" \
    "io.qt.PySide.BaseApp//${BRANCH}"
}

echo "==> flatpak-builder --user --install"
rm -rf "${BUILD_DIR}"
flatpak-builder \
  --user \
  --install \
  --force-clean \
  --state-dir="${STATE_DIR}" \
  --repo="${REPO_DIR}" \
  "${BUILD_DIR}" \
  "${ROOT}/io.aipc.CodexBarGui.yml"

echo "==> Refresh desktop database"
update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "${HOME}/.local/share/flatpak/exports/share/icons/hicolor" 2>/dev/null || true

echo
echo "Installed: ${APP_ID}"
flatpak info "${APP_ID}" 2>/dev/null || flatpak info --user "${APP_ID}"
echo
echo "Run:  flatpak run ${APP_ID}"
echo "Apps: look for “CodexBar” in the application menu"
echo "Host codexbar CLI must remain on PATH (shim uses flatpak-spawn --host)"
