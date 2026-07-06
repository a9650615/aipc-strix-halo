"""Active-window-class lookup for the D4 blacklist check.

Wayland has no cross-compositor "get focused window" call. KWin's own
DBus interface (`org.kde.KWin` on the session bus) was checked directly on
this machine and does NOT expose it cleanly: `queryWindowInfo()` blocks
waiting for an interactive pointer click (not usable headless) and
`getWindowInfo(uuid)` needs a uuid we don't have. `kdotool` (Fedora package
`kdotool`, "xdotool-like tool to manipulate windows on KDE Wayland") wraps
KWin's scripting API to do this properly and is the native-platform choice
(CLAUDE.md ladder rung 4) over hand-rolling a KWin script + journal-scrape.

ponytail: kdotool is declared in packages.txt but is NOT installed on this
dev host, and could not be installed live to test here either — this
machine boots a read-only ostree/composefs image (`rpm -q`/`dnf search`
work, but `dnf install`/`rpm --rebuilddb` fail with "read-only file
system" on /usr), so a real install only happens through an image
rebuild, matching CLAUDE.md's build-time/runtime split. This module is
therefore STATIC-ONLY for window-class detection until a hardware-verified
pass after a real `bootc switch` confirms kdotool's actual subcommand
output on this box. Upgrade path: only this file's subprocess calls would
need adjusting if kdotool's CLI shape differs from what's assumed below.
"""

import subprocess

KDOTOOL = "kdotool"


def get_active_window_class() -> str | None:
    """Best-effort KWin active window class, or None if it can't be
    determined (kdotool missing, no active window, any subprocess error).
    Callers must treat None as "unknown" and fail closed (see gate.py) —
    never assume "no class" means "not blacklisted"."""
    try:
        win_id = subprocess.run(
            [KDOTOOL, "getactivewindow"],
            capture_output=True, text=True, timeout=2,
        )
        if win_id.returncode != 0 or not win_id.stdout.strip():
            return None
        cls = subprocess.run(
            [KDOTOOL, "getwindowclassname", win_id.stdout.strip()],
            capture_output=True, text=True, timeout=2,
        )
        if cls.returncode != 0 or not cls.stdout.strip():
            return None
        return cls.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
