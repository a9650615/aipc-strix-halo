from __future__ import annotations

import json

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


def test_ensure_panels_script_creates_panels_with_autohide() -> None:
    script = desktop_presets.ensure_panels_script(2)
    assert "screenCount = 2" in script
    assert "haveBottom[ps[i].screen] = true" in script
    assert 'p.hiding = "autohide"' in script
    assert 't.hiding = "autohide"' in script


def test_ensure_panels_script_forces_autohide_on_existing_panels_too() -> None:
    # Regression: "none"/"dodgewindows" reserve strut space and squeeze
    # fullscreen windows down to fit around the panel (2026-07-04 bug
    # report) -- every apply must re-force autohide on panels that already
    # existed before this preset ran, not just newly created ones.
    script = desktop_presets.ensure_panels_script(1)
    assert 'ps[j].hiding = "autohide"' in script


def test_apply_preset_unknown_name_raises_key_error() -> None:
    try:
        desktop_presets.apply_preset("does-not-exist", runner=lambda *a, **k: _FakeCompletedProcess())
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_apply_preset_mac_runs_expected_commands() -> None:
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["kscreen-doctor", "-j"]:
            return _FakeCompletedProcess(stdout=json.dumps({"outputs": [{"connected": True, "enabled": True}]}))
        return _FakeCompletedProcess(0)

    desktop_presets.apply_preset("mac", runner=fake_runner)

    assert any(c[:2] == ["kwriteconfig6", "--file"] for c in calls)
    assert any(c[0] == "qdbus" and "PlasmaShell" in c[2] for c in calls)
    assert any(c[0] == "qdbus" and c[2] == "/KWin" for c in calls)
