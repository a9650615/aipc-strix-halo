#!/usr/bin/env python3
"""Test script to verify CodexBar GUI logic without running actual GUI.

This script tests:
- Module imports
- Server communication
- Data fetching
- Icon generation
- Config loading
"""

import sys
import json
import urllib.request
from pathlib import Path

# Add GUI directory to path
GUI_DIR = Path(__file__).parent
sys.path.insert(0, str(GUI_DIR))


def test_imports():
    """Test that all GUI modules can be imported."""
    print("Testing imports...")
    try:
        from codexbar_gui.tray_app import CodexBarApp
        from codexbar_gui.usage_panel import UsagePanel
        from codexbar_gui.icon_updater import generate_svg, get_color_for_percent
        from codexbar_gui.config_dialog import ConfigDialog
        from codexbar_gui.server_launcher import check_server, start_server
        from codexbar_gui.config import load_config
        print("✓ All modules imported successfully")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False


def test_server():
    """Test HTTP server communication."""
    print("\nTesting server communication...")
    try:
        # Try to connect to server
        response = urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5)
        data = json.loads(response.read())
        print(f"✓ Server healthy: {data.get('status')}")
        
        # Fetch usage data
        response = urllib.request.urlopen("http://127.0.0.1:8080/usage", timeout=10)
        data = json.loads(response.read())
        print(f"✓ Fetched {len(data)} providers")
        return True
    except Exception as e:
        print(f"✗ Server test failed: {e}")
        print("  (Server may not be running - this is OK for testing)")
        return False


def test_config():
    """Test config loading."""
    print("\nTesting config...")
    try:
        from codexbar_gui.config import load_config
        config = load_config()
        print(f"✓ Config loaded: refresh_interval={config.refresh_interval}, icon_size={config.icon_size}")
        return True
    except Exception as e:
        print(f"✗ Config test failed: {e}")
        return False


def test_icon_generation():
    """Test SVG icon generation."""
    print("\nTesting icon generation...")
    try:
        from codexbar_gui.icon_updater import generate_svg, get_color_for_percent
        
        # Test color for different usage levels
        colors = [
            (0, "green"),
            (50, "yellow"),
            (80, "red"),
            (100, "red"),
        ]
        
        for percent, expected_color in colors:
            color = get_color_for_percent(percent)
            print(f"  {percent}%: {color}")
        
        # Generate SVG
        svg = generate_svg(0.5)
        print(f"✓ SVG generated ({len(svg)} bytes)")
        return True
    except Exception as e:
        print(f"✗ Icon test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("CodexBar GUI - Logic Tests")
    print("=" * 60)
    
    results = []
    results.append(("Imports", test_imports()))
    results.append(("Server", test_server()))
    results.append(("Config", test_config()))
    results.append(("Icons", test_icon_generation()))
    
    print("\n" + "=" * 60)
    print("Results:")
    print("=" * 60)
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
    
    all_passed = all(r[1] for r in results)
    print("=" * 60)
    if all_passed:
        print("All tests passed! ✓")
        return 0
    else:
        print("Some tests failed. ✗")
        return 1


if __name__ == "__main__":
    sys.exit(main())
