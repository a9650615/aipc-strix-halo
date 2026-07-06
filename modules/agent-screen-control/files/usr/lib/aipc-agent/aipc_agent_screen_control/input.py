"""ydotool wrapper for the Coder/Browser sub-agents (phase-4-agent#4.7).

ydotool over xdotool: this machine runs kwin_wayland (native Wayland);
xdotool only reliably targets XWayland-mapped windows. ydotool injects
through /dev/uinput via the `ydotoold` daemon, so it works regardless of
compositor. `ydotool.service` is already enabled on this box, listening at
`/run/user/1000/.ydotool_socket` (hardware-verified: `ydotool mousemove 0 0`
exits 0 as the regular user, no sudo).

Every function here calls gate.check_action() FIRST and lets its exceptions
(GateDenied, BlacklistedWindow) propagate — no action ever shells out to
ydotool before that check passes. This is the actual security property
task 4.7 asks for; do not add a call path that skips it.
"""

import subprocess

from aipc_agent_screen_control import gate

YDOTOOL = "ydotool"


def mouse_move(x: int, y: int) -> None:
    gate.check_action()
    subprocess.run([YDOTOOL, "mousemove", "--absolute", str(x), str(y)], check=True)


def mouse_click(button: str = "left") -> None:
    gate.check_action()
    # ydotool click codes: 0xC0 left, 0xC1 right, 0xC2 middle
    code = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}[button]
    subprocess.run([YDOTOOL, "click", code], check=True)


def key_type(text: str) -> None:
    gate.check_action()
    subprocess.run([YDOTOOL, "type", text], check=True)


def key_press(key: str) -> None:
    """`key` is a ydotool keycode name/combo, e.g. "28:1" style is raw
    keycodes — ydotool's own `key` subcommand also accepts names like
    "KEY_ENTER" via its keycode table; pass through verbatim."""
    gate.check_action()
    subprocess.run([YDOTOOL, "key", key], check=True)


def self_test() -> None:
    """ponytail: no target-window state on this host to safely click/type
    into for real (see README safety note), so this only proves the
    fail-closed path: with no gate socket present, every action must raise
    GateDenied before touching ydotool at all."""
    for fn, args in [
        (mouse_move, (0, 0)),
        (mouse_click, ()),
        (key_type, ("x",)),
        (key_press, ("KEY_ENTER",)),
    ]:
        try:
            fn(*args)
            raise AssertionError(f"{fn.__name__} did not fail closed with no gate")
        except gate.GateDenied:
            pass
    print("self-test passed (fail-closed with no gate socket present)")


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
