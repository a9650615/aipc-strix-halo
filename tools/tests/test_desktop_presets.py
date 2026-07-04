from __future__ import annotations

import json
from pathlib import Path

from aipc_lib import desktop_presets


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_list_presets_includes_mac() -> None:
    names = [p.name for p in desktop_presets.list_presets()]
    assert "mac" in names


def test_window_buttons_mac_style_commands_put_buttons_on_left() -> None:
    cmds = desktop_presets.window_buttons_mac_style_commands()
    assert ["kwriteconfig6", "--file", "kwinrc", "--group", "org.kde.kdecoration2", "--key", "ButtonsOnLeft", "XIA"] in cmds
    assert ["kwriteconfig6", "--file", "kwinrc", "--group", "org.kde.kdecoration2", "--key", "ButtonsOnRight", ""] in cmds


def test_touchpad_mac_style_commands_target_the_real_device_group() -> None:
    cmds = desktop_presets.touchpad_mac_style_commands()
    keys = {cmd[-2] for cmd in cmds}
    assert keys == {"NaturalScroll", "TapToClick"}
    for cmd in cmds:
        assert desktop_presets.TOUCHPAD_NAME in cmd
        assert cmd[-1] == "true"


def test_connected_screen_count_counts_only_connected_and_enabled() -> None:
    payload = {
        "outputs": [
            {"connected": True, "enabled": True},
            {"connected": True, "enabled": False},
            {"connected": False, "enabled": False},
        ]
    }

    def fake_runner(cmd, **kwargs):
        return _FakeCompletedProcess(stdout=json.dumps(payload))

    assert desktop_presets.connected_screen_count(runner=fake_runner) == 1


def test_ensure_panels_script_creates_visible_panels_by_default() -> None:
    # Regression: hiding="autohide" on every panel unconditionally hides the
    # Dock/top bar even on a screen with no fullscreen window at all
    # (2026-07-04 bug report #2). New panels must default to "none"
    # (visible) -- fullscreen-autohide-panels.kwinscript is what switches a
    # screen to "autohide", and only while something on it is fullscreen.
    script = desktop_presets.ensure_panels_script(2)
    assert "screenCount = 2" in script
    assert "haveBottom[ps[i].screen] = true" in script
    assert 'p.hiding = "none"' in script
    assert 't.hiding = "none"' in script
    assert "autohide" not in script


def test_install_kwin_script_writes_metadata_and_main_js(tmp_path: Path) -> None:
    desktop_presets.install_kwin_script(tmp_path)
    script_dir = tmp_path / ".local/share/kwin/scripts" / desktop_presets.KWIN_SCRIPT_ID
    metadata = json.loads((script_dir / "metadata.json").read_text())
    assert metadata["KPackageStructure"] == "KWin/Script"
    assert metadata["KPlugin"]["Id"] == desktop_presets.KWIN_SCRIPT_ID
    main_js = (script_dir / "contents/code/main.js").read_text()
    assert "workspace.windowActivated.connect(recheck)" in main_js
    assert "window.fullScreenChanged" in main_js


def test_apply_preset_unknown_name_raises_key_error(tmp_path: Path) -> None:
    try:
        desktop_presets.apply_preset("does-not-exist", tmp_path, runner=lambda *a, **k: _FakeCompletedProcess())
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_apply_preset_mac_runs_expected_commands_and_installs_script(tmp_path: Path) -> None:
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["kscreen-doctor", "-j"]:
            return _FakeCompletedProcess(stdout=json.dumps({"outputs": [{"connected": True, "enabled": True}]}))
        return _FakeCompletedProcess(0)

    desktop_presets.apply_preset("mac", tmp_path, runner=fake_runner)

    assert any(c[:2] == ["kwriteconfig6", "--file"] for c in calls)
    assert any(c[0] == "qdbus" and "PlasmaShell" in c[2] for c in calls)
    assert any(c[0] == "qdbus" and c[2] == "/KWin" for c in calls)
    script_dir = tmp_path / ".local/share/kwin/scripts" / desktop_presets.KWIN_SCRIPT_ID
    assert (script_dir / "metadata.json").exists()
