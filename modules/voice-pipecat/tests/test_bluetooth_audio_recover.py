#!/usr/bin/env python3
import unittest
from subprocess import CompletedProcess

from aipc_bluetooth_audio_recover import (
    connect_with_bluez_fallback,
    connect_with_retries,
    device_path_from_tree,
    has_sink,
    needs_recovery,
    needs_connection,
    power_cycle_adapter,
    set_default_sink,
    sink_name,
)


class BluetoothAudioRecoveryTests(unittest.TestCase):
    def test_builds_sink_name_from_mac(self):
        self.assertEqual(
            sink_name("68:52:10:35:29:44"),
            "bluez_output.68_52_10_35_29_44.1",
        )

    def test_detects_exact_pipewire_sink(self):
        output = "59697\tbluez_output.68_52_10_35_29_44.1\tPipeWire\ts16le 2ch"
        self.assertTrue(has_sink(output, "68:52:10:35:29:44"))
        self.assertFalse(has_sink(output, "AA:BB:CC:DD:EE:FF"))

    def test_finds_device_on_any_bluetooth_adapter(self):
        tree = """
        ├─ /org/bluez/hci0
        └─ /org/bluez/hci1/dev_68_52_10_35_29_44
        """
        self.assertEqual(
            device_path_from_tree(tree, "68:52:10:35:29:44"),
            "/org/bluez/hci1/dev_68_52_10_35_29_44",
        )
        self.assertEqual(device_path_from_tree(tree, "AA:BB:CC:DD:EE:FF"), "")

    def test_recovers_only_paired_connected_device_without_sink(self):
        self.assertTrue(
            needs_recovery(
                paired=True,
                connected=True,
                pactl_output="",
                mac="68:52:10:35:29:44",
            )
        )
        self.assertFalse(
            needs_recovery(
                paired=True,
                connected=False,
                pactl_output="",
                mac="68:52:10:35:29:44",
            )
        )

    def test_restarts_bluez_once_when_connect_fails(self):
        calls = []

        def run(argv):
            calls.append(argv)
            if argv[-1] == "Connect" and calls.count(argv) == 1:
                return CompletedProcess(argv, 1, "", "br-connection-create-socket")
            return CompletedProcess(argv, 0, "", "")

        def output(argv):
            if argv[:2] == ["busctl", "tree"]:
                return "/org/bluez/hci1/dev_68_52_10_35_29_44\n"
            return ""

        self.assertEqual(
            connect_with_bluez_fallback(
                "/org/bluez/hci1/dev_68_52_10_35_29_44",
                "68:52:10:35:29:44",
                run=run,
                output=output,
            ),
            "/org/bluez/hci1/dev_68_52_10_35_29_44",
        )
        self.assertIn(["systemctl", "restart", "bluetooth"], calls)

    def test_autoconnects_paired_device_without_restarting_audio(self):
        self.assertTrue(
            needs_connection(
                paired=True,
                pactl_output="",
                mac="68:52:10:35:29:44",
            )
        )
        self.assertFalse(
            needs_connection(
                paired=False,
                pactl_output="",
                mac="68:52:10:35:29:44",
            )
        )

    def test_power_cycles_the_adapter(self):
        calls = []

        def run(argv):
            calls.append(argv)
            return CompletedProcess(argv, 0, "", "")

        self.assertTrue(
            power_cycle_adapter(
                "/org/bluez/hci1/dev_68_52_10_35_29_44",
                run=run,
            )
        )
        self.assertEqual(
            calls,
            [
                [
                    "busctl",
                    "set-property",
                    "org.bluez",
                    "/org/bluez/hci1",
                    "org.bluez.Adapter1",
                    "Powered",
                    "b",
                    "false",
                ],
                [
                    "busctl",
                    "set-property",
                    "org.bluez",
                    "/org/bluez/hci1",
                    "org.bluez.Adapter1",
                    "Powered",
                    "b",
                    "true",
                ],
            ],
        )
        self.assertFalse(
            needs_recovery(
                paired=True,
                connected=True,
                pactl_output="1\tbluez_output.68_52_10_35_29_44.1\tPipeWire",
                mac="68:52:10:35:29:44",
            )
        )

    def test_retries_connect_until_a2dp_endpoints_are_ready(self):
        attempts = {"n": 0}

        def run(argv):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return CompletedProcess(argv, 1, "", "Protocol not available")
            return CompletedProcess(argv, 0, "", "")

        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)

        self.assertTrue(
            connect_with_retries(
                "/org/bluez/hci1/dev_68_52_10_35_29_44",
                timeout=30.0,
                run=run,
                clock=lambda: 0.0,
                sleep=sleep,
            )
        )
        self.assertEqual(attempts["n"], 2)
        self.assertEqual(sleeps, [2.0])

    def test_gives_up_after_bounded_window_when_connect_never_succeeds(self):
        attempts = {"n": 0}

        def run(argv):
            attempts["n"] += 1
            return CompletedProcess(argv, 1, "", "Protocol not available")

        clock_values = iter([0.0, 5.0, 35.0])

        def clock():
            return next(clock_values)

        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)

        self.assertFalse(
            connect_with_retries(
                "/org/bluez/hci1/dev_68_52_10_35_29_44",
                timeout=30.0,
                run=run,
                clock=clock,
                sleep=sleep,
            )
        )
        self.assertEqual(attempts["n"], 2)
        self.assertEqual(sleeps, [2.0])

    def test_sets_default_sink_by_name(self):
        calls = []

        def run(argv):
            calls.append(argv)
            return CompletedProcess(argv, 0, "", "")

        self.assertTrue(set_default_sink("bluez_output.test.1", run=run))
        self.assertEqual(calls, [["pactl", "set-default-sink", "bluez_output.test.1"]])


if __name__ == "__main__":
    unittest.main()
