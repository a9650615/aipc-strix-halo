#!/usr/bin/env python3
"""Recover a paired Bluetooth speaker stuck without a PipeWire A2DP sink."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

DEFAULT_MAC = "68:52:10:35:29:44"
SINK_TIMEOUT = 45.0


def sink_name(mac: str) -> str:
    return f"bluez_output.{mac.replace(':', '_')}.1"


def has_sink(pactl_output: str, mac: str) -> bool:
    target = sink_name(mac)
    return any(
        len(fields) > 1 and fields[1] == target
        for fields in (line.split() for line in pactl_output.splitlines())
    )


def needs_recovery(
    *, paired: bool, connected: bool, pactl_output: str, mac: str
) -> bool:
    return connected and needs_connection(paired=paired, pactl_output=pactl_output, mac=mac)


def needs_connection(*, paired: bool, pactl_output: str, mac: str) -> bool:
    return paired and not has_sink(pactl_output, mac)


def device_path_from_tree(tree: str, mac: str) -> str:
    device = re.escape(f"dev_{mac.replace(':', '_')}")
    match = re.search(rf"(/org/bluez/hci\d+/{device})(?=\s|$)", tree)
    return match.group(1) if match else ""


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, text=True, capture_output=True, check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def set_default_sink(sink: str, *, run=_run) -> bool:
    return run(["pactl", "set-default-sink", sink]).returncode == 0


def _output(argv: list[str]) -> str:
    return _run(argv).stdout


def _property(device: str, name: str) -> bool:
    output = _output(
        [
            "busctl",
            "get-property",
            "org.bluez",
            device,
            "org.bluez.Device1",
            name,
        ]
    )
    return bool(output) and output.split()[-1].lower() == "true"


def _wait(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.5)
    return bool(predicate())


def connect_with_bluez_fallback(
    device: str,
    mac: str,
    *,
    run=_run,
    output=_output,
) -> str:
    connect_args = [
        "busctl",
        "call",
        "org.bluez",
        device,
        "org.bluez.Device1",
        "Connect",
    ]
    if run(connect_args).returncode == 0:
        return device
    if run(["systemctl", "restart", "bluetooth"]).returncode != 0:
        return ""
    refreshed = device_path_from_tree(output(["busctl", "tree", "org.bluez"]), mac)
    if not refreshed:
        return ""
    connect_args[3] = refreshed
    if run(connect_args).returncode == 0:
        return refreshed
    if not power_cycle_adapter(refreshed, run=run):
        return ""
    refreshed = device_path_from_tree(output(["busctl", "tree", "org.bluez"]), mac)
    if not refreshed:
        return ""
    connect_args[3] = refreshed
    return refreshed if run(connect_args).returncode == 0 else ""


def power_cycle_adapter(device: str, *, run=_run) -> bool:
    adapter = device.rsplit("/", 1)[0]
    prefix = [
        "busctl",
        "set-property",
        "org.bluez",
        adapter,
        "org.bluez.Adapter1",
        "Powered",
        "b",
    ]
    if run([*prefix, "false"]).returncode != 0:
        return False
    return run([*prefix, "true"]).returncode == 0


def recover(mac: str = DEFAULT_MAC, timeout: float = SINK_TIMEOUT) -> int:
    tree = _output(["busctl", "tree", "org.bluez"])
    device = device_path_from_tree(tree, mac)
    if not device:
        return 0

    pactl_output = _output(["pactl", "list", "short", "sinks"])
    paired = _property(device, "Paired")
    connected = _property(device, "Connected")
    if not paired or has_sink(pactl_output, mac):
        return 0

    if not connected:
        direct = _run(["busctl", "call", "org.bluez", device, "org.bluez.Device1", "Connect"])
        if direct.returncode != 0:
            return 0
        sink = sink_name(mac)
        if _wait(
            lambda: has_sink(_output(["pactl", "list", "short", "sinks"]), mac),
            timeout,
        ):
            return 0 if set_default_sink(sink) else 1
        connected = _property(device, "Connected")
        if not connected:
            return 0

    print(f"aipc-bluetooth-audio-recover: repairing {mac}", file=sys.stderr)
    restarted = _run(
        [
            "systemctl",
            "--user",
            "restart",
            "wireplumber.service",
            "pipewire-pulse.service",
            "pipewire.service",
        ]
    )
    if restarted.returncode != 0:
        print(
            "aipc-bluetooth-audio-recover: audio restart failed",
            file=sys.stderr,
        )
        return 1

    disconnected = _run(["busctl", "call", "org.bluez", device, "org.bluez.Device1", "Disconnect"])
    if disconnected.returncode != 0:
        print("aipc-bluetooth-audio-recover: disconnect failed", file=sys.stderr)
        return 1
    if not _wait(lambda: not _property(device, "Connected"), 10.0):
        print("aipc-bluetooth-audio-recover: disconnect timed out", file=sys.stderr)
        return 1

    device = connect_with_bluez_fallback(device, mac)
    if not device:
        print("aipc-bluetooth-audio-recover: connect failed", file=sys.stderr)
        return 1
    sink = sink_name(mac)
    if not _wait(
        lambda: has_sink(_output(["pactl", "list", "short", "sinks"]), mac),
        timeout,
    ):
        print(f"aipc-bluetooth-audio-recover: {sink} did not appear", file=sys.stderr)
        return 1

    if not set_default_sink(sink):
        print("aipc-bluetooth-audio-recover: set-default failed", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--self-test"]:
        assert sink_name(DEFAULT_MAC) == "bluez_output.68_52_10_35_29_44.1"
        assert not needs_recovery(
            paired=True,
            connected=True,
            pactl_output="1 bluez_output.68_52_10_35_29_44.1 PipeWire",
            mac=DEFAULT_MAC,
        )
        return 0
    if args:
        print(f"usage: {sys.argv[0]} [--self-test]", file=sys.stderr)
        return 2
    return recover(os.environ.get("AIPC_BLUETOOTH_AUDIO_MAC", DEFAULT_MAC))


if __name__ == "__main__":
    raise SystemExit(main())
