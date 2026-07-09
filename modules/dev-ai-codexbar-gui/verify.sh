#!/bin/sh
set -eu

# Verify the codexbar-gui module structure and imports.

echo "=== CodexBar GUI Module Verification ==="

# Check module directory exists
if [ ! -d "modules/dev-ai-codexbar-gui" ]; then
    echo "ERROR: module directory not found" >&2
    exit 1
fi

# Check required files exist
required_files=(
    "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui/codexbar_gui/__init__.py"
    "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui/codexbar_gui/tray_app.py"
    "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui/codexbar_gui/usage_panel.py"
    "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui/codexbar_gui/icon_updater.py"
    "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui/codexbar_gui/config_dialog.py"
    "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui/codexbar_gui/server_launcher.py"
    "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui/pyproject.toml"
    "modules/dev-ai-codexbar-gui/packages.txt"
    "modules/dev-ai-codexbar-gui/post-install.sh"
    "modules/dev-ai-codexbar-gui/verify.sh"
)

for file in "${required_files[@]}"; do
    if [ ! -f "$file" ]; then
        echo "ERROR: missing $file" >&2
        exit 1
    fi
done

echo "✓ All required files present"

# Check packages.txt has PySide6
if ! grep -q "pyside6" "modules/dev-ai-codexbar-gui/packages.txt"; then
    echo "ERROR: packages.txt missing PySide6" >&2
    exit 1
fi
echo "✓ PySide6 dependency declared"

# Check packages.txt has PyYAML (needed by config.py)
if ! grep -q "pyyaml" "modules/dev-ai-codexbar-gui/packages.txt"; then
    echo "ERROR: packages.txt missing PyYAML" >&2
    exit 1
fi
echo "✓ PyYAML dependency declared"

# Check desktop file exists
if [ ! -f "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui/codexbar-gui.desktop" ]; then
    echo "ERROR: desktop file missing" >&2
    exit 1
fi
echo "✓ Desktop file present"

# Check autostart directory
if [ ! -d "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui/autostart" ]; then
    echo "ERROR: autostart directory missing" >&2
    exit 1
fi
echo "✓ Autostart directory present"

# Verify Python syntax of all modules
cd "modules/dev-ai-codexbar-gui/files/usr/lib/codexbar-gui"
python3 -m py_compile codexbar_gui/__init__.py
python3 -m py_compile codexbar_gui/tray_app.py
python3 -m py_compile codexbar_gui/usage_panel.py
python3 -m py_compile codexbar_gui/icon_updater.py
python3 -m py_compile codexbar_gui/config_dialog.py
python3 -m py_compile codexbar_gui/server_launcher.py
cd - > /dev/null
echo "✓ All Python modules compile successfully"

echo ""
echo "dev-ai-codexbar-gui: verification passed"
