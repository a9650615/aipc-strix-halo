from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Legacy: this preset used to ship a KWin script (fullscreen-hides-panels)
# that dynamically toggled panel hiding based on per-window fullscreen state.
# After several iterations it still didn't reliably work (user, 2026-07-04:
# "還是沒有解決任何問題" -- still hasn't solved anything). Replaced with a
# static policy: dock is never-hide (same as the top bar), on every screen.
# (2026-07-06, two iterations: first shipped as "autohide", which
# macOS-Dock-style always hides regardless of overlap and only reveals on
# hover -- not what was wanted ("為什麼我沒有遮擋還是會隱藏"). Switched to
# "dodgewindows" (hide only when a window actually overlaps it) -- but a
# maximized window's geometry covers the dock's strip by definition, so
# double-click-to-maximize kept hiding it too, still not wanted. Landed on
# "none": same as the top bar, it reserves its own strut so ordinary window
# maximize stops short of it instead of covering it; hardware-verified this
# leaves the dock visible through maximize. A genuinely fullscreen window
# (games, video players) still overrides the strut and covers it -- that's
# the compositor's own exclusive-fullscreen behavior, unrelated to this
# per-panel `.hiding` setting.)
# This id is kept only so apply_preset can find and remove a previously
# installed copy (see uninstall_legacy_kwin_script / disable_legacy_kwin_script_command).
LEGACY_KWIN_SCRIPT_ID = "fullscreen-hides-panels"

# GZ302EA-specific: this repo targets one fixed hardware model (CLAUDE.md §6),
# so hardcoding this exact touchpad's libinput vendor/product id follows the
# same pattern as other hardware-specific workarounds already in this repo
# (amdgpu.dcdebugmask, GPP0/GPP1 wake fix) rather than being a portability
# shortcut.
TOUCHPAD_VENDOR = "2821"
TOUCHPAD_PRODUCT = "6704"
TOUCHPAD_NAME = "ASUSTeK Computer Inc. GZ302EA-Keyboard Touchpad"

RunnerT = Callable[..., subprocess.CompletedProcess]

# Relative to $HOME. Tracks each screen's last-seen synced value so
# reconcile_widget_config can tell "this screen just changed" apart from
# "everyone still matches" -- see that function's docstring. Separate files
# per (location, widget_type, config_key) combination -- they track
# independent values and must not clobber each other's state.
DOCK_LAUNCHER_STATE_RELPATH = Path(".local/state/aipc/dock-launcher-sync.json")
TOPBAR_SYSTEMTRAY_STATE_RELPATH = Path(".local/state/aipc/topbar-systemtray-sync.json")


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


def disable_legacy_kwin_script_command() -> list[str]:
    """Turn off the old fullscreen-detecting KWin script if it was ever
    enabled on this machine -- it would otherwise fight the static
    hiding policy applied by ensure_panels_script."""
    return [
        "kwriteconfig6",
        "--file",
        "kwinrc",
        "--group",
        "Plugins",
        "--key",
        f"{LEGACY_KWIN_SCRIPT_ID}Enabled",
        "false",
    ]


def unload_legacy_kwin_script_command() -> list[str]:
    """Hardware-verified 2026-07-04: disabling a script in kwinrc + `KWin
    reconfigure` does NOT stop an already-running instance -- `isScriptLoaded`
    stayed true and its old per-window fullscreen signal handlers kept firing,
    silently overwriting the static hiding policy moments after apply_preset
    finished. `org.kde.kwin.Scripting.unloadScript` is the only thing that
    actually stops a live instance immediately."""
    return [
        "qdbus",
        "org.kde.KWin",
        "/Scripting",
        "org.kde.kwin.Scripting.unloadScript",
        LEGACY_KWIN_SCRIPT_ID,
    ]


def uninstall_legacy_kwin_script(home: Path) -> None:
    script_root = home / ".local/share/kwin/scripts" / LEGACY_KWIN_SCRIPT_ID
    if script_root.exists():
        shutil.rmtree(script_root)


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
    for screens that don't have one yet, then apply a static hiding policy
    to every bottom/top panel on every screen.

    NON-DESTRUCTIVE to widgets/layout (user spec 2026-07-04: "preset 布局不要
    去動 dock app 那塊, 使用者放什麼就是什麼" -- the preset must not touch the
    dock's app content; whatever the user places stays). Existing panels'
    widget lists are left completely untouched -- pinned launchers /
    task-manager entries live inside a widget's own config, which a
    destroy-and-recreate would silently wipe. So this only *creates* panels
    on screens that lack one; it never removes or rewrites an existing
    panel's widgets.

    Consequence, stated plainly: this syncs layout to a new/bare screen at
    creation time (clone of the primary's current structure), but does NOT
    continuously reconcile already-populated screens' widget lists back into
    lockstep -- that would mean clobbering exactly the per-screen dock
    content the user asked to preserve. To re-clone a screen's widgets from
    scratch, remove its panels by hand first, then re-run.

    2026-07-06 update, direct user request ("dock app 項目同步", later refined
    to "哪一個 change, 就 sync 到全部的 dock"): the 07-04 spec above turned out
    too broad in practice -- a second screen's Dock with no pinned launchers
    just looks broken, not "whatever the user placed". apply_preset now
    calls reconcile_dock_launchers() as one narrow, explicit exception: it
    overwrites only the `launchers` value, propagating whichever screen's
    list changed most recently to every other screen. Everything else
    (widget list, other per-widget config) stays covered by the
    non-destructive rule above.

    Hiding policy is the one thing this DOES force on every panel, new or
    existing, every apply (setting `.hiding` never touches widgets so it
    doesn't conflict with the non-destructive rule above). Direct user spec
    2026-07-04, after the fullscreen-detecting KWin script repeatedly failed
    to work ("還是沒有解決任何問題"): "每個螢幕的 dock 都設定自動隱藏, 選單列
    永遠不隱藏就好了". Landed on "none" (same as the top bar) after two wrong
    guesses, both hardware-verified wrong by direct user report on
    2026-07-06: "autohide" always hides regardless of overlap and only
    reveals on hover ("為什麼自動隱藏現在我沒有遮擋還是會隱藏"); "dodgewindows"
    hides whenever a window overlaps it, but a maximized window's geometry
    always does, so double-click-to-maximize kept hiding it too. "none"
    reserves the dock's own strut so ordinary maximize stops short of it --
    genuinely fullscreen windows (games, video players) still cover it via
    the compositor's own exclusive-fullscreen path, independent of this
    setting. Note: the Panel scripting API silently accepts invalid
    `.hiding` string literals and falls back to "none" instead of raising --
    "windowscover" and "windowsgobelow" (natural-sounding guesses) are NOT
    valid values; "autohide", "dodgewindows" and "none" are the confirmed set.
    Every screen's Dock (bottom panel) and top bar both use "none".
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

function applySpec(panel, location, spec, hiding) {{
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
  panel.hiding = hiding;
  for (var i = 0; i < spec.widgets.length; i++) {{ panel.addWidget(spec.widgets[i]); }}
}}

for (var s = 0; s < screenCount; s++) {{
  if (!haveBottom[s]) {{
    var p = new Panel;
    p.screen = s;
    applySpec(p, "bottom", bottomSpec, "none");
  }}
  if (!haveTop[s]) {{
    var t = new Panel;
    t.screen = s;
    applySpec(t, "top", topSpec, "none");
  }}
}}

for (var i = 0; i < ps.length; i++) {{
  if (ps[i].location === "bottom") ps[i].hiding = "none";
  if (ps[i].location === "top") ps[i].hiding = "none";
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


def _find_widgets_script(location: str, widget_type: str) -> str:
    """Prints "<panelId>,<appletId>;<panelId>,<appletId>;..." for every
    screen's <location> panel's <widget_type> widget."""
    return f"""\
var ps = panels();
var out = [];
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].location !== "{location}") continue;
  var widgets = ps[i].widgets();
  for (var j = 0; j < widgets.length; j++) {{
    if (widgets[j].type === "{widget_type}") {{
      out.push(ps[i].id + "," + widgets[j].id);
    }}
  }}
}}
print(out.join(";"));
"""


def _find_widgets_command(location: str, widget_type: str) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        _find_widgets_script(location, widget_type),
    ]


def all_dock_icontasks_ids_script() -> str:
    """Prints "<panelId>,<appletId>;<panelId>,<appletId>;..." for every
    screen's Dock (bottom panel) icontasks widget -- the pinned launcher
    list lives per-widget-instance, so a screen without a launchers= key
    just shows an empty Dock with no way to pin an app short of doing it by
    hand on that screen specifically. No primary/replica distinction here;
    that's for reconcile_widget_config to decide from state, not this."""
    return _find_widgets_script("bottom", "org.kde.plasma.icontasks")


def all_dock_icontasks_ids_command() -> list[str]:
    return _find_widgets_command("bottom", "org.kde.plasma.icontasks")


# Default config-group path under an Applet, for widgets whose QML declares
# a configGroup (icontasks and most others). systemtray is the one common
# exception -- hardware-verified 2026-07-06: its extraItems/knownItems live
# directly under [General], one level shallower, no [Configuration] wrapper.
DEFAULT_CONFIG_GROUPS = ("Configuration", "General")


def _read_config_value(
    panel_id: str, applet_id: str, key: str, runner: RunnerT, config_groups: tuple[str, ...] = DEFAULT_CONFIG_GROUPS
) -> str:
    cmd = ["kreadconfig6", "--file", "plasma-org.kde.plasma.desktop-appletsrc"]
    for g in ("Containments", panel_id, "Applets", applet_id, *config_groups):
        cmd += ["--group", g]
    cmd += ["--key", key]
    return runner(cmd, capture_output=True, text=True, check=True).stdout.strip()


def _read_launchers(panel_id: str, applet_id: str, runner: RunnerT) -> str:
    return _read_config_value(panel_id, applet_id, "launchers", runner)


def reconcile_widget_config(
    location: str,
    widget_type: str,
    config_key: str,
    state_path: Path,
    runner: RunnerT = subprocess.run,
    config_groups: tuple[str, ...] = DEFAULT_CONFIG_GROUPS,
) -> None:
    """Direct user request 2026-07-06 ("其中一個 dock 做變更, 就自動 sync 到全部
    的 dock", later "top bar 也同步"): whichever screen's <location> panel's
    <widget_type> widget had <config_key> edited since the last run,
    propagate it to every other screen's same widget. No primary/replica
    distinction -- genuinely symmetric, last-writer-wins, so it's meant to
    be triggered by a systemd path unit watching the appletsrc file (kernel
    inotify, not a hand-rolled polling loop -- see the removed
    aipc-sync-plasma.service for what that looked like and why it was torn
    out) as well as being called once from apply_preset. Originally
    dock-launchers-specific (reconcile_dock_launchers); generalized so the
    same mechanism covers the top bar's systemtray icon list without a
    second copy of this logic.

    state_path holds the last-seen value per panel id as JSON, so a run can
    tell "did panel X change since last time" apart from "everyone still
    matches, nothing to do" -- without that, every trigger (including the
    one caused by this function's own writes) would look like a change and
    loop forever. Each (location, widget_type, config_key) combination needs
    its own state_path -- they track independent values.

    ponytail: if two screens are edited in the same interval between
    trigger runs, which one wins is arbitrary (lowest panel id) -- only
    matters if you edit two screens within the same debounce window, which
    a path-unit trigger (fires within ~seconds of the write) makes rare.
    """
    result = runner(_find_widgets_command(location, widget_type), capture_output=True, text=True, check=True)
    pairs = [tuple(ref.split(",")) for ref in result.stdout.strip().split(";") if ref]
    if len(pairs) < 2:
        return

    current = {
        panel_id: _read_config_value(panel_id, applet_id, config_key, runner, config_groups)
        for panel_id, applet_id in pairs
    }

    previous: dict[str, str] = {}
    if state_path.exists():
        previous = json.loads(state_path.read_text())

    changed = sorted(pid for pid, value in current.items() if pid in previous and previous[pid] != value)

    if changed:
        canonical = current[changed[0]]
        for panel_id, applet_id in pairs:
            if current[panel_id] != canonical:
                runner(
                    _kwriteconfig(
                        "plasma-org.kde.plasma.desktop-appletsrc",
                        ["Containments", panel_id, "Applets", applet_id, *config_groups],
                        config_key,
                        canonical,
                    ),
                    check=True,
                )
        current = {pid: canonical for pid in current}

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(current))


def reconcile_dock_launchers(state_path: Path, runner: RunnerT = subprocess.run) -> None:
    reconcile_widget_config("bottom", "org.kde.plasma.icontasks", "launchers", state_path, runner)


def reconcile_topbar_systemtray(state_path: Path, runner: RunnerT = subprocess.run) -> None:
    """Same mechanism as reconcile_dock_launchers, for the top bar's
    systemtray icon visibility list (`extraItems=`) instead of the Dock's
    pinned launchers -- toggling which tray icons show is the top-bar
    equivalent of pinning/unpinning a Dock launcher. Hardware-verified
    2026-07-06: systemtray stores extraItems directly under [General], not
    [Configuration][General] like icontasks' launchers -- hence the
    different config_groups here."""
    reconcile_widget_config(
        "top", "org.kde.plasma.systemtray", "extraItems", state_path, runner, config_groups=("General",)
    )


def panel_widget_sync_unit_files(aipc_path: str) -> dict[str, str]:
    """Unit file contents keyed by filename. PathModified= is kernel inotify,
    not a hand-rolled polling loop -- see the torn-out aipc-sync-plasma.service
    (dead code, a sed/awk polling script) for what that looked like and why
    it was removed. The .service is a oneshot with two ExecStart lines (both
    run in order on every trigger) -- Dock launchers and top-bar systemtray
    icons are two independent reconcile_widget_config() calls, not one, but
    both watch the same appletsrc file so one path unit covers both."""
    return {
        "aipc-panel-widget-sync.path": """[Unit]
Description=Watch KDE panel config for Dock/top-bar widget changes

[Path]
PathModified=%h/.config/plasma-org.kde.plasma.desktop-appletsrc

[Install]
WantedBy=default.target
""",
        "aipc-panel-widget-sync.service": f"""[Unit]
Description=Reconcile Dock/top-bar per-screen widget config

[Service]
Type=oneshot
ExecStart={aipc_path} config preset sync-dock-launchers
ExecStart={aipc_path} config preset sync-topbar-systemtray
""",
    }


def install_panel_widget_sync_units(home: Path, runner: RunnerT = subprocess.run) -> None:
    """Direct user request 2026-07-06 ("其中一個 dock 做變更, 就自動 sync 到全部
    的 dock", later "top bar 也同步", "本來就應該通用"): install + enable a
    systemd --user path unit so reconcile_widget_config runs automatically
    on every panel-config change, not only when `aipc config preset apply`
    is run by hand. Resolves the `aipc` binary's actual path at install time
    via shutil.which rather than hardcoding /usr/local/bin/aipc (the
    shipped-image path per commit 11a9db9) -- a pipx dev install like this
    machine's lives at ~/.local/bin/aipc instead, and systemd user services
    don't inherit that onto PATH by default. Idempotent: re-writing
    identical unit files and re-running `enable --now` on an already-enabled
    unit are both no-ops."""
    aipc_path = shutil.which("aipc") or "aipc"
    unit_dir = home / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)

    # Superseded name (2026-07-06, same day): dock-launchers-only, before
    # the top-bar systemtray reconcile was added under the same trigger.
    runner(["systemctl", "--user", "disable", "--now", "aipc-dock-launcher-sync.path"], check=False)
    for old in ("aipc-dock-launcher-sync.path", "aipc-dock-launcher-sync.service"):
        (unit_dir / old).unlink(missing_ok=True)

    for name, content in panel_widget_sync_unit_files(aipc_path).items():
        (unit_dir / name).write_text(content)
    runner(["systemctl", "--user", "daemon-reload"], check=False)
    runner(["systemctl", "--user", "enable", "--now", "aipc-panel-widget-sync.path"], check=False)


# Canonical Dock widget order, hardware-verified 2026-07-06 against this
# machine's actual dock layout (both screens, before anything drifted).
# rebuild_dock_panel() always recreates in exactly this order -- there's no
# per-screen customization point here, matching ensure_panels_script's own
# stance of a fixed structure rather than something users are expected to
# reorder per screen.
DOCK_WIDGET_ORDER = [
    "org.kde.plasma.kickoff",
    "org.kde.plasma.pager",
    "org.kde.plasma.icontasks",
    "org.kde.plasma.marginsseparator",
    "org.kde.plasma.folder",
    "org.kde.plasma.showdesktop",
    "org.kde.plasma.systemmonitor",
]


def find_dock_script(screen: int) -> str:
    """Prints "<panelId>,<icontasksAppletId>" for the given screen's Dock,
    or nothing if that screen has none."""
    return f"""\
var ps = panels();
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].screen !== {screen} || ps[i].location !== "bottom") continue;
  var widgets = ps[i].widgets();
  for (var j = 0; j < widgets.length; j++) {{
    if (widgets[j].type === "org.kde.plasma.icontasks") {{
      print(ps[i].id + "," + widgets[j].id);
    }}
  }}
}}
"""


def find_dock_command(screen: int) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        find_dock_script(screen),
    ]


def rebuild_dock_script(screen: int) -> str:
    """Destroy-and-recreate the given screen's Dock in DOCK_WIDGET_ORDER,
    preserving the panel's own geometry (read from itself just before
    destroying it). Prints "<newPanelId>,<newIcontasksAppletId>" so the
    caller can write the preserved launchers value onto the fresh instance.

    Hardware-verified 2026-07-06 this is the only thing that reliably fixes
    BOTH of reconcile_dock_launchers' known gaps at once: icontasks doesn't
    live-reload an externally-written `launchers` value (Applet.reloadConfig()
    hardware-verified NOT to help, unlike simpler config-bound properties),
    and AppletOrder doesn't take effect live either (same as
    ensure_panels_script's top-bar-reorder finding) -- so widget-level
    remove+recreate fixes content but not order, while THIS (panel-level)
    fixes both, at the cost of a bigger blast radius (every widget on that
    one panel gets recreated, not just icontasks).

    Known cost, not a bug: a freshly created org.kde.plasma.icontasks seeds
    itself with Plasma's own default pins (org.kde.discover.desktop showed
    up as a real example) independent of anything in the `launchers` config
    key -- writing launchers again afterward does NOT remove it, since it's
    not coming from that key. One manual unpin clears it and it does not
    come back unless the panel is rebuilt again. This only runs on explicit
    request (not from the automatic path-unit trigger) precisely because of
    this cost -- rebuilding on every reconcile would reintroduce it constantly.
    """
    widgets_json = json.dumps(DOCK_WIDGET_ORDER)
    return f"""\
var ps = panels();
var old = null;
for (var i = 0; i < ps.length; i++) {{
  if (ps[i].screen === {screen} && ps[i].location === "bottom") old = ps[i];
}}
if (!old) {{
  print("");
}} else {{
  var spec = {{
    alignment: old.alignment, offset: old.offset, lengthMode: old.lengthMode,
    length: old.length, height: old.height, floating: old.floating, opacity: old.opacity
  }};
  old.remove();
  var p = new Panel;
  p.screen = {screen};
  p.location = "bottom";
  p.alignment = spec.alignment;
  p.offset = spec.offset;
  p.lengthMode = spec.lengthMode;
  if (spec.lengthMode !== "fit" && spec.lengthMode !== "fill" && spec.length > 0) p.length = spec.length;
  p.height = spec.height;
  p.floating = spec.floating;
  p.opacity = spec.opacity;
  p.hiding = "none";
  var order = {widgets_json};
  var icontasksId = -1;
  for (var i = 0; i < order.length; i++) {{
    var w = p.addWidget(order[i]);
    if (order[i] === "org.kde.plasma.icontasks") icontasksId = w.id;
  }}
  print(p.id + "," + icontasksId);
}}
"""


def rebuild_dock_command(screen: int) -> list[str]:
    return [
        "qdbus",
        "org.kde.plasmashell",
        "/PlasmaShell",
        "org.kde.PlasmaShell.evaluateScript",
        rebuild_dock_script(screen),
    ]


def find_dock_panel(screen: int, runner: RunnerT = subprocess.run) -> tuple[str, str] | None:
    result = runner(find_dock_command(screen), capture_output=True, text=True, check=True)
    ref = result.stdout.strip()
    if not ref:
        return None
    panel_id, applet_id = ref.split(",")
    return panel_id, applet_id


def rebuild_dock_panel(screen: int, runner: RunnerT = subprocess.run) -> str | None:
    """Direct user request 2026-07-06 ("重建時直接 filter 掉" / "那把其他螢幕的
    dock 完全重建不就好了"): rebuild one screen's Dock from scratch in the
    canonical order, preserving its current pinned-launcher list. Returns a
    warning string about the Discover-reseed cost (see rebuild_dock_script)
    if the rebuild happened, or None if that screen had no Dock to rebuild.
    """
    found = find_dock_panel(screen, runner)
    if found is None:
        return None
    old_panel_id, old_applet_id = found
    launchers = _read_launchers(old_panel_id, old_applet_id, runner)

    result = runner(rebuild_dock_command(screen), capture_output=True, text=True, check=True)
    new_ref = result.stdout.strip()
    if not new_ref:
        return None
    new_panel_id, new_applet_id = new_ref.split(",")

    if launchers:
        runner(
            _kwriteconfig(
                "plasma-org.kde.plasma.desktop-appletsrc",
                ["Containments", new_panel_id, "Applets", new_applet_id, "Configuration", "General"],
                "launchers",
                launchers,
            ),
            check=True,
        )
    for key in ("minimizeActiveTaskOnClick", "showOnlyCurrentDesktop"):
        runner(
            _kwriteconfig(
                "plasma-org.kde.plasma.desktop-appletsrc",
                ["Containments", new_panel_id, "Applets", new_applet_id, "Configuration", "General"],
                key,
                "false",
            ),
            check=True,
        )
    return (
        "Dock rebuilt. If a Discover (or other unexpected) icon shows up, "
        "that's Plasma's own default seed for a fresh icontasks widget, not "
        "a config bug -- unpin it by hand once; it won't come back unless "
        "this screen's Dock is rebuilt again."
    )


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
            "cloned across screens, Dock (bottom panel) and top bar both "
            "reserve their space and never hide, on every screen "
            "(GZ302EA touchpad id hardcoded)"
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
    uninstall_legacy_kwin_script(home)
    runner(disable_legacy_kwin_script_command(), check=False)
    runner(unload_legacy_kwin_script_command(), check=False)
    screen_count = connected_screen_count(runner)
    primary_x, primary_y = primary_screen_position(runner)
    runner(ensure_panels_command(screen_count, primary_x, primary_y), check=True)
    reconcile_dock_launchers(home / DOCK_LAUNCHER_STATE_RELPATH, runner)
    reconcile_topbar_systemtray(home / TOPBAR_SYSTEMTRAY_STATE_RELPATH, runner)
    runner(reconfigure_kwin_command(), check=False)
    install_panel_widget_sync_units(home, runner)
