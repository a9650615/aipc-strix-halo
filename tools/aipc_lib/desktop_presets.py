from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

KWIN_SCRIPT_ID = "fullscreen-hides-dock"

_METADATA_JSON = """{
    "KPackageStructure": "KWin/Script",
    "KPlugin": {
        "Authors": [{"Name": "aipc"}],
        "Description": "Hides a screen's Dock only while a window on that specific screen is truly fullscreen; the Dock and top bar are otherwise always visible on every screen",
        "Icon": "preferences-system-windows-script-test",
        "Id": "fullscreen-hides-dock",
        "License": "MIT",
        "Name": "Fullscreen Hides Dock"
    },
    "X-Plasma-API": "javascript"
}
"""

# Went through several designs in one session (2026-07-04) trying to make the
# Dock/top bar only show on the focused screen -- each fix uncovered another
# bug (forgetting to reset other screens, not tracking pre-existing windows,
# an un-verifiable fix), and the whole "which screen is focused" tracking
# turned out to not even be what was wanted. Direct user feedback: "頂部選單列
# 要常駐,dock focus 才出現 or 做不到的話就常駐也沒關係" (top bar should be
# persistent; Dock only on focus, or if that can't be done, persistent is
# fine too) -- given how much fragility the focus-tracking version had, this
# takes the offered simpler fallback instead of continuing to chase it:
#
#   - Top bar: always visible on every screen, hiding="none" set once at
#     panel creation, never touched again. No script involvement.
#   - Dock: always visible (hiding="none") *except* on whichever specific
#     screen currently has an active window that is truly fullscreen --
#     that screen's Dock (only that one) switches to "autohide" so the
#     fullscreen window isn't squeezed by reserved strut space (the one part
#     of the original "Mac experience" request that's an actual visual bug,
#     not a preference).
#
# This only ever needs to know, for the window that was just
# activated/toggled, which single screen it's on -- no more "reset every
# other screen too" step, which removes the riskiest and buggiest part of
# the previous design.
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

function updateDockForScreen(screenIdx, fullScreen) {
    var script =
        "var ps = panels();" +
        "for (var i = 0; i < ps.length; i++) {" +
        "  var p = ps[i];" +
        "  if (p.location === 'bottom' && p.screen === " + screenIdx + ") {" +
        "    p.hiding = " + (fullScreen ? "'autohide'" : "'none'") + ";" +
        "  }" +
        "}";
    callDBus("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell", "evaluateScript", script);
}

function recheck(window) {
    if (!window || !window.output) {
        return;
    }
    updateDockForScreen(findOutputIndex(window.output), !!window.fullScreen);
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
    """Plasma evaluateScript source: the primary screen's *current* Dock +
    top bar (whatever the user has actually configured for it via the GUI)
    is the single source of truth -- clone its panel properties and widget
    list onto every other connected screen, replacing anything already
    there.

    Every apply removes *all* existing bottom/top panels first and
    recreates them from the primary screen's spec (not idempotent-by-
    skipping on purpose -- an earlier "only create if this screen doesn't
    already have one" version let a screen's panel drift out of sync with
    the others, reported as "layout broken" on that screen). If the primary
    screen has no bottom/top panel yet (first-ever run), falls back to a
    reasonable default spec so there's something to clone next time.

    Both panels default to `hiding = "none"` (always visible) -- the top
    bar stays that way permanently; fullscreen-hides-dock.kwinscript then
    autohides only a screen's Dock, only while that screen actually has a
    fullscreen window.
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
for (var i = 0; i < ps.length; i++) {{
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

ps = panels();
for (var i = ps.length - 1; i >= 0; i--) {{
  if (ps[i].location === "bottom" || ps[i].location === "top") {{
    ps[i].remove();
  }}
}}
for (var s = 0; s < screenCount; s++) {{
  var p = new Panel;
  p.screen = s;
  applySpec(p, "bottom", bottomSpec);

  var t = new Panel;
  t.screen = s;
  applySpec(t, "top", topSpec);
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
            "natural-scroll + tap-to-click touchpad, top bar always "
            "visible, Dock always visible except autohidden on a screen "
            "while it has a truly fullscreen window (GZ302EA touchpad id "
            "hardcoded)"
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
