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


def test_primary_screen_position_picks_lowest_priority_output() -> None:
    payload = {
        "outputs": [
            {"connected": True, "enabled": True, "priority": 2, "pos": {"x": 0, "y": 0}},
            {"connected": True, "enabled": True, "priority": 1, "pos": {"x": 331, "y": 1271}},
        ]
    }

    def fake_runner(cmd, **kwargs):
        return _FakeCompletedProcess(stdout=json.dumps(payload))

    assert desktop_presets.primary_screen_position(runner=fake_runner) == (331, 1271)


def test_ensure_panels_script_clones_primary_screens_current_panel() -> None:
    script = desktop_presets.ensure_panels_script(2, 331, 1271)
    assert "screenCount = 2" in script
    assert "g.x === 331 && g.y === 1271" in script
    assert "function readSpec(panel)" in script
    assert "org.kde.plasma.kickoff" in script


def test_ensure_panels_script_is_non_destructive_to_existing_panels() -> None:
    # User spec 2026-07-04: "preset 布局不要去動 dock app 那塊, 使用者放什麼就是
    # 什麼" -- the preset must not wipe the dock's app content. A
    # destroy-and-recreate silently loses pinned launchers / task-manager
    # entries (they live in a widget's own config), so the script must only
    # CREATE panels where a screen lacks one and never remove/rewrite an
    # existing panel's widgets.
    script = desktop_presets.ensure_panels_script(2, 0, 0)
    assert "remove()" not in script
    assert "if (!haveBottom[s])" in script
    assert "if (!haveTop[s])" in script


def test_ensure_panels_script_applies_static_hiding_policy() -> None:
    # Direct user spec 2026-07-04, after the fullscreen-detecting KWin script
    # repeatedly failed: "每個螢幕的 dock 都設定自動隱藏, 選單列永遠不隱藏就好
    # 了". Landed on "none" (same as the top bar) after two wrong guesses,
    # both hardware-verified wrong by direct user report on 2026-07-06:
    # "autohide" always hides regardless of overlap, only reveals on hover
    # ("為什麼自動隱藏現在我沒有遮擋還是會隱藏"); "dodgewindows" hides whenever a
    # window overlaps it, but a maximized window always does, so
    # double-click-to-maximize kept hiding it too ("視窗點兩下最大化但是不隱藏
    # dock"). "none" reserves the dock's own strut so ordinary maximize stops
    # short of it -- hardware-verified the dock stays visible through
    # maximize ("dock 還在"). Applied both to newly-created panels and to
    # every pre-existing panel (setting .hiding never touches widgets, so it
    # doesn't conflict with the non-destructive rule above).
    script = desktop_presets.ensure_panels_script(2, 0, 0)
    assert 'applySpec(p, "bottom", bottomSpec, "none")' in script
    assert 'applySpec(t, "top", topSpec, "none")' in script
    assert 'if (ps[i].location === "bottom") ps[i].hiding = "none";' in script
    assert 'if (ps[i].location === "top") ps[i].hiding = "none";' in script


def test_icontasks_launcher_ids_script_targets_bottom_panel_icontasks() -> None:
    script = desktop_presets.icontasks_launcher_ids_script(2, 331, 1271)
    assert "screenCount = 2" in script
    assert "g.x === 331 && g.y === 1271" in script
    assert 'widgets[j].type !== "org.kde.plasma.icontasks"' in script
    assert 'ps[i].location !== "bottom"' in script


def test_sync_dock_launchers_copies_primary_list_to_other_screens() -> None:
    # Direct user request 2026-07-06 ("dock app 項目同步"): a screen without
    # a launchers= key just shows an empty Dock. Hardware-verified the ids
    # discovery + kreadconfig6 + kwriteconfig6 sequence live before landing
    # this in the repo.
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "qdbus":
            return _FakeCompletedProcess(stdout="365,368:473,476;999,111")
        if cmd[0] == "kreadconfig6":
            return _FakeCompletedProcess(stdout="applications:systemsettings.desktop,preferred://filemanager")
        return _FakeCompletedProcess(0)

    desktop_presets.sync_dock_launchers(2, 0, 0, fake_runner)

    write_calls = [c for c in calls if c[0] == "kwriteconfig6"]
    assert len(write_calls) == 2
    for panel_id, applet_id in [("473", "476"), ("999", "111")]:
        assert any(
            c[-1] == "applications:systemsettings.desktop,preferred://filemanager"
            and panel_id in c
            and applet_id in c
            for c in write_calls
        )


def test_sync_dock_launchers_noop_when_only_one_screen() -> None:
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(stdout="365,368:")

    desktop_presets.sync_dock_launchers(1, 0, 0, fake_runner)

    assert not any(c[0] in ("kreadconfig6", "kwriteconfig6") for c in calls)


def test_sync_dock_launchers_noop_when_primary_has_no_launchers_pinned() -> None:
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "qdbus":
            return _FakeCompletedProcess(stdout="365,368:473,476")
        return _FakeCompletedProcess(stdout="")

    desktop_presets.sync_dock_launchers(2, 0, 0, fake_runner)

    assert not any(c[0] == "kwriteconfig6" for c in calls)


def test_disable_legacy_kwin_script_command_targets_old_script_id() -> None:
    cmd = desktop_presets.disable_legacy_kwin_script_command()
    assert cmd == [
        "kwriteconfig6",
        "--file",
        "kwinrc",
        "--group",
        "Plugins",
        "--key",
        f"{desktop_presets.LEGACY_KWIN_SCRIPT_ID}Enabled",
        "false",
    ]


def test_uninstall_legacy_kwin_script_removes_directory_if_present(tmp_path: Path) -> None:
    script_dir = tmp_path / ".local/share/kwin/scripts" / desktop_presets.LEGACY_KWIN_SCRIPT_ID
    (script_dir / "contents/code").mkdir(parents=True)
    (script_dir / "metadata.json").write_text("{}")

    desktop_presets.uninstall_legacy_kwin_script(tmp_path)

    assert not script_dir.exists()


def test_uninstall_legacy_kwin_script_is_a_noop_if_absent(tmp_path: Path) -> None:
    desktop_presets.uninstall_legacy_kwin_script(tmp_path)


def test_unload_legacy_kwin_script_command_calls_scripting_interface() -> None:
    # Hardware-verified 2026-07-04: disabling in kwinrc alone left the old
    # script's isScriptLoaded() == true and its live signal handlers kept
    # firing, overwriting the new static hiding policy. Only an explicit
    # unloadScript() call actually stops it.
    cmd = desktop_presets.unload_legacy_kwin_script_command()
    assert cmd == [
        "qdbus",
        "org.kde.KWin",
        "/Scripting",
        "org.kde.kwin.Scripting.unloadScript",
        desktop_presets.LEGACY_KWIN_SCRIPT_ID,
    ]


def test_apply_preset_unknown_name_raises_key_error(tmp_path: Path) -> None:
    try:
        desktop_presets.apply_preset("does-not-exist", tmp_path, runner=lambda *a, **k: _FakeCompletedProcess())
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_apply_preset_mac_runs_expected_commands_and_cleans_up_legacy_script(tmp_path: Path) -> None:
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["kscreen-doctor", "-j"]:
            return _FakeCompletedProcess(
                stdout=json.dumps(
                    {"outputs": [{"connected": True, "enabled": True, "priority": 1, "pos": {"x": 0, "y": 0}}]}
                )
            )
        return _FakeCompletedProcess(0)

    script_dir = tmp_path / ".local/share/kwin/scripts" / desktop_presets.LEGACY_KWIN_SCRIPT_ID
    (script_dir / "contents/code").mkdir(parents=True)
    (script_dir / "metadata.json").write_text("{}")

    desktop_presets.apply_preset("mac", tmp_path, runner=fake_runner)

    assert any(c[:2] == ["kwriteconfig6", "--file"] for c in calls)
    assert any(c[0] == "qdbus" and "PlasmaShell" in c[2] for c in calls)
    assert any(c[0] == "qdbus" and c[2] == "/KWin" for c in calls)
    assert any(c[-2:] == [f"{desktop_presets.LEGACY_KWIN_SCRIPT_ID}Enabled", "false"] for c in calls)
    assert any(c[-2:] == ["org.kde.kwin.Scripting.unloadScript", desktop_presets.LEGACY_KWIN_SCRIPT_ID] for c in calls)
    assert not script_dir.exists()
