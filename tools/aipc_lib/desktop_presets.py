from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

KWIN_SCRIPT_ID = "fullscreen-hides-panels"

_METADATA_JSON = """{
    "KPackageStructure": "KWin/Script",
    "KPlugin": {
        "Authors": [{"Name": "aipc"}],
        "Description": "Hides both the Dock and top bar on a screen while a window on that specific screen is truly fullscreen; both are otherwise always visible, per-screen independent",
        "Icon": "preferences-system-windows-script-test",
        "Id": "fullscreen-hides-panels",
        "License": "MIT",
        "Name": "Fullscreen Hides Panels"
    },
    "X-Plasma-API": "javascript"
}
"""

# Final design (2026-07-04), after several buggier focus-tracking attempts.
# Direct user spec: "有全螢幕 app 的部份 頂部底部就隱藏, 沒有就顯示, 每個螢幕的
# 隱藏設定是分離的" (a screen with a fullscreen app hides both top and bottom;
# without one, shows both; each screen's hide state is independent):
#
#   - Both the top bar and the Dock on a given screen are visible
#     (hiding="none") by default, and switch to "autohide" together while
#     that screen has a truly fullscreen window -- so the fullscreen app
#     isn't squeezed by reserved strut space.
#   - Per-screen and independent: the script only ever touches the single
#     screen the just-activated/toggled window is on, so each screen's
#     hide state reflects its own fullscreen situation with no cross-screen
#     coupling (that coupling was the source of the earlier bugs).
#
# Layout (widget list, size, position) stays unified across screens, but
# that's handled separately at apply time by cloning the primary screen's
# panels (see ensure_panels_script), NOT by this script.
_MAIN_JS = """\
function findOutputIndex(output) {
    var screens = workspace.screens;
    for (var i = 0; i < screens.length; i++) {
        if (screens[i] === output) {
            return i;
        }
    }
    return 0;
}

function updatePanelsForScreen(screenIdx, fullScreen) {
    var script =
        "var ps = panels();" +
        "for (var i = 0; i < ps.length; i++) {" +
        "  var p = ps[i];" +
        "  if ((p.location === 'bottom' || p.location === 'top') && p.screen === " + screenIdx + ") {" +
        "    p.hiding = " + (fullScreen ? "'autohide'" : "'none'") + ";" +
        "  }" +
        "}";
    callDBus("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell", "evaluateScript", script);
}

function recheck(window) {
    if (!window || !window.output) {
        return;
    }
    updatePanelsForScreen(findOutputIndex(window.output), !!window.fullScreen);
}

function trackWindow(window) {
    if (!window || !window.fullScreenChanged) {
        return;
    }
    window.fullScreenChanged.connect(function () {
        recheck(window);
    });
}

workspace.windowActivated.connect(recheck);
workspace.windowAdded.connect(trackWindow);

// workspace.windowAdded only fires for windows created after this script
// loads -- walk every already-open window too (workspace.stackingOrder),
// or toggling fullscreen on one does nothing until an unrelated event
// forces a recheck.
var existing = workspace.stackingOrder;
for (var i = 0; i < existing.length; i++) {
    trackWindow(existing[i]);
}

if (workspace.activeWindow) {
    recheck(workspace.activeWindow);
}
"""

# GZ302EA-specific: this repo targets one fixed hardware model (CLAUDE.md §6),
# so hardcoding this exact touchpad's libinput vendor/product id follows the
# same pattern as other hardware-specific workarounds already in this repo
# (amdgpu.dcdebugmask, GPP0/GPP1 wake fix) rather than being a portability
# shortcut.
TOUCHPAD_VENDOR = "2821"
TOUCHPAD_PRODUCT = "6704"
TOUCHPAD_NAME = "ASUSTeK Computer Inc. GZ302EA-Keyboard Touchpad"

RunnerT = Callable[..., subprocess.CompletedProcess]


def _kwriteconfig(file: str, groups: list[str], key: str, value: str) -> list[str]:
    cmd = ["kwriteconfig6", "--file", file]
    for g in groups:
        cmd += ["--group", g]
    cmd += ["--key", key, value]
    return cmd


def window_buttons_mac_style_commands() -> list[list[str]]:
    """Close/minimize/maximize on the left, Mac order (close, minimize, maximize)."""
    return [
        _kwriteconfig("kwinrc", ["org.kde.kdecoration2"], "ButtonsOnLeft", "XIA"),
        _kwriteconfig("kwinrc", ["org.kde.kdecoration2"], "ButtonsOnRight", ""),
    ]


def touchpad_mac_style_commands() -> list[list[str]]:
    """Tap-to-click + natural scrolling. NOTE: libinput properties only take
    effect after logout/login, not live -- a KDE/KWin limitation, not
    something this can force from the CLI."""
    groups = ["Libinput", TOUCHPAD_VENDOR, TOUCHPAD_PRODUCT, TOUCHPAD_NAME]
    return [
        _kwriteconfig("kcminputrc", groups, "NaturalScroll", "true"),
        _kwriteconfig("kcminputrc", groups, "TapToClick", "true"),
    ]


def enable_kwin_script_command() -> list[str]:
    return [
        "kwriteconfig6",
        "--file",
        "kwinrc",
        "--group",
        "Plugins",
        "--key",
        f"{KWIN_SCRIPT_ID}Enabled",
        "true",
    ]


def install_kwin_script(home: Path) -> None:
    script_root = home / ".local/share/kwin/scripts" / KWIN_SCRIPT_ID
    code_dir = script_root / "contents/code"
    code_dir.mkdir(parents=True, exist_ok=True)
    (script_root / "metadata.json").write_text(_METADATA_JSON)
    (code_dir / "main.js").write_text(_MAIN_JS)


def connected_screen_count(runner: RunnerT = subprocess.run) -> int:
    result = runner(["kscreen-doctor", "-j"], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return sum(1 for o in data.get("outputs", []) if o.get("connected") and o.get("enabled"))


def primary_screen_position(runner: RunnerT = subprocess.run) -> tuple[int, int]:
    """(x, y) layout position of the primary output (lowest `priority`),
    per `kscreen-doctor -j`. This is the same coordinate space as Plasma's
    scripting `screenGeometry(i).x/.y`, so the two can be matched up to find
    which Plasma panel `.screen` index is the primary display."""
    result = runner(["kscreen-doctor", "-j"], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    outputs = [o for o in data.get("outputs", []) if o.get("connected") and o.get("enabled")]
    primary = min(outputs, key=lambda o: o.get("priority", 999))
    pos = primary["pos"]
    return pos["x"], pos["y"]


def ensure_panels_script(screen_count: int, primary_x: int, primary_y: int) -> str:
    """Plasma evaluateScript source: give every connected screen a Dock +
    top bar, cloning the primary screen's *current* panels as the template
    for screens that don't have one yet.

    NON-DESTRUCTIVE by design (user spec 2026-07-04: "preset 布局不要去動 dock
    app 那塊, 使用者放什麼就是什麼" -- the preset must not touch the dock's app
    content; whatever the user places stays). Existing bottom/top panels are
    left completely untouched -- pinned launchers / task-manager entries live
    inside a widget's own config, which a destroy-and-recreate would silently
    wipe. So this only *creates* panels on screens that lack one; it never
    removes or rewrites an existing panel.

    Consequence, stated plainly: this syncs layout to a new/bare screen at
    creation time (clone of the primary's current structure), but does NOT
    continuously reconcile already-populated screens back into lockstep --
    that would mean clobbering exactly the per-screen dock content the user
    asked to preserve. To re-clone a screen from scratch, remove its panels
    by hand first, then re-run.

    If the primary screen has no bottom/top panel yet (first-ever run),
    falls back to a reasonable default template. New panels are created with
    `hiding = "none"` (always visible); fullscreen-hides-panels.kwinscript
    then autohides both of a screen's panels together, per-screen
    independent, only while that screen actually has a fullscreen window.
    """
    return f"""\
var screenCount = {screen_count};
var primaryIdx = 0;
for (var i = 0; i < screenCount; i++) {{
  var g = screenGeometry(i);
  if (g.x === {primary_x} && g.y === {primary_y}) {{
    primaryIdx = i;
    break;
  }}
}}

function readSpec(panel) {{
  var widgets = panel.widgets();
  var types = [];
  for (var i = 0; i < widgets.length; i++) {{ types.push(widgets[i].type); }}
  return {{
    alignment: panel.alignment, offset: panel.offset, lengthMode: panel.lengthMode,
    length: panel.length, height: panel.height, floating: panel.floating,
    opacity: panel.opacity, widgets: types
  }};
}}

var ps = panels();
var bottomSpec = null, topSpec = null;
var haveBottom = {{}}, haveTop = {{}};
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].location === "bottom") haveBottom[ps[i].screen] = true;
  if (ps[i].location === "top") haveTop[ps[i].screen] = true;
  if (ps[i].screen !== primaryIdx) continue;
  if (ps[i].location === "bottom") bottomSpec = readSpec(ps[i]);
  if (ps[i].location === "top") topSpec = readSpec(ps[i]);
}}

if (!bottomSpec) {{
  bottomSpec = {{
    alignment: "center", offset: 0, lengthMode: "fit", length: 0, height: 44,
    floating: true, opacity: "adaptive",
    widgets: ["org.kde.plasma.kickoff", "org.kde.plasma.pager", "org.kde.plasma.icontasks",
              "org.kde.plasma.marginsseparator", "org.kde.plasma.folder"]
  }};
}}
if (!topSpec) {{
  topSpec = {{
    alignment: "center", offset: 0, lengthMode: "fill", length: 0, height: 30,
    floating: false, opacity: "translucent",
    widgets: ["org.kde.plasma.digitalclock", "org.kde.plasma.showdesktop",
              "org.kde.plasma.systemtray", "org.kde.plasma.battery", "org.kde.plasma.panelspacer"]
  }};
}}

function applySpec(panel, location, spec) {{
  panel.location = location;
  panel.alignment = spec.alignment;
  panel.offset = spec.offset;
  panel.lengthMode = spec.lengthMode;
  if (spec.lengthMode !== "fit" && spec.lengthMode !== "fill" && spec.length > 0) {{
    panel.length = spec.length;
  }}
  panel.height = spec.height;
  panel.floating = spec.floating;
  panel.opacity = spec.opacity;
  panel.hiding = "none";
  for (var i = 0; i < spec.widgets.length; i++) {{ panel.addWidget(spec.widgets[i]); }}
}}

for (var s = 0; s < screenCount; s++) {{
  if (!haveBottom[s]) {{
    var p = new Panel;
    p.screen = s;
    applySpec(p, "bottom", bottomSpec);
  }}
  if (!haveTop[s]) {{
    var t = new Panel;
    t.screen = s;
    applySpec(t, "top", topSpec);
  }}
}}
"""


def ensure_panels_command(screen_count: int, primary_x: int, primary_y: int) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        ensure_panels_script(screen_count, primary_x, primary_y),
    ]


def reconfigure_kwin_command() -> list[str]:
    return ["qdbus", "org.kde.KWin", "/KWin", "reconfigure"]


@dataclass
class Preset:
    name: str
    description: str


PRESETS: dict[str, Preset] = {
    "mac": Preset(
        name="mac",
        description=(
            "macOS-like KDE Plasma desktop: window buttons on the left, "
            "natural-scroll + tap-to-click touchpad, unified panel layout "
            "cloned across screens, Dock + top bar visible per-screen "
            "except both autohidden on a screen while it has a truly "
            "fullscreen window (GZ302EA touchpad id hardcoded)"
        ),
    ),
}


def list_presets() -> list[Preset]:
    return list(PRESETS.values())


def apply_preset(name: str, home: Path, runner: RunnerT = subprocess.run) -> None:
    if name not in PRESETS:
        raise KeyError(name)
    for cmd in window_buttons_mac_style_commands():
        runner(cmd, check=True)
    for cmd in touchpad_mac_style_commands():
        runner(cmd, check=True)
    install_kwin_script(home)
    runner(enable_kwin_script_command(), check=True)
    screen_count = connected_screen_count(runner)
    primary_x, primary_y = primary_screen_position(runner)
    runner(ensure_panels_command(screen_count, primary_x, primary_y), check=True)
    runner(reconfigure_kwin_command(), check=False)
