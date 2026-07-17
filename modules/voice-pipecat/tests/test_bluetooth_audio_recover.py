#!/usr/bin/env python3
import unittest
from subprocess import CompletedProcess

from aipc_bluetooth_audio_recover import (
    connect_with_bluez_fallback,
    connect_with_retries,
    device_path_from_tree,
    has_sink,
    is_recovery_event,
    monitor,
    recover_safe,
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

    def _safe_output(self, *, connected="b true\n", sinks=""):
        def output(argv):
            if argv[:2] == ["busctl", "tree"]:
                return "/org/bluez/hci0/dev_68_52_10_35_29_44\n"
            if argv[:2] == ["busctl", "get-property"]:
                return connected
            if argv[:3] == ["pactl", "list", "short"]:
                return sinks
            return ""

        return output

    def _record_run(self, calls):
        def run(argv):
            calls.append(argv)
            return CompletedProcess(argv, 0, "", "")

        return run

    def test_recover_safe_is_silent_when_healthy(self):
        calls = []
        self.assertEqual(
            recover_safe(
                "68:52:10:35:29:44",
                run=self._record_run(calls),
                output=self._safe_output(
                    sinks="1\tbluez_output.68_52_10_35_29_44.1\tPipeWire"
                ),
            ),
            0,
        )
        self.assertEqual(calls, [])

    def test_recover_safe_does_nothing_when_disconnected(self):
        calls = []
        self.assertEqual(
            recover_safe(
                "68:52:10:35:29:44",
                run=self._record_run(calls),
                output=self._safe_output(connected="b false\n", sinks=""),
            ),
            0,
        )
        self.assertEqual(calls, [])

    def test_recover_safe_only_notifies_and_never_touches_bt_or_audio(self):
        calls = []
        self.assertEqual(
            recover_safe(
                "68:52:10:35:29:44",
                run=self._record_run(calls),
                output=self._safe_output(connected="b true\n", sinks=""),
            ),
            1,
        )
        self.assertEqual([c[0] for c in calls], ["notify-send"])
        self.assertFalse(
            any(
                c[:1] == ["systemctl"]
                or c[:2] == ["busctl", "call"]
                or "Powered" in c
                for c in calls
            )
        )

    def test_matches_only_relevant_device_property_events(self):
        dev = "dev_68_52_10_35_29_44"
        connected = f"/org/bluez/hci0/{dev}: ...PropertiesChanged ('org.bluez.Device1', {{'Connected': <true>}}, @as [])"
        resolved = f"/org/bluez/hci0/{dev}: ...PropertiesChanged ('org.bluez.Device1', {{'ServicesResolved': <true>}}, @as [])"
        self.assertTrue(is_recovery_event(connected, "68:52:10:35:29:44"))
        self.assertTrue(is_recovery_event(resolved, "68:52:10:35:29:44"))
        self.assertFalse(is_recovery_event(connected, "AA:BB:CC:DD:EE:FF"))
        self.assertFalse(
            is_recovery_event(
                f"/org/bluez/hci0/{dev}: ...PropertiesChanged ('org.bluez.Device1', {{'RSSI': <-42>}}, @as [])",
                "68:52:10:35:29:44",
            )
        )

    def test_monitor_recovers_on_startup_and_on_each_event(self):
        events = [
            "unrelated line\n",
            "/org/bluez/hci0/dev_68_52_10_35_29_44: PropertiesChanged 'Connected' <true>\n",
            "/org/bluez/hci0/dev_68_52_10_35_29_44: PropertiesChanged 'ServicesResolved' <true>\n",
        ]

        class FakeProc:
            stdout = iter(events)

            def wait(self):
                return 0

        recoveries = []
        # clock() order: init last, then (check, update) per firing event;
        # gaps must exceed MONITOR_COOLDOWN (60s) so both events fire
        ticks = iter([0.0, 70.0, 70.0, 140.0, 140.0])

        self.assertEqual(
            monitor(
                "68:52:10:35:29:44",
                popen=lambda *a, **k: FakeProc(),
                clock=lambda: next(ticks),
                sleep=lambda _s: None,
                recover=lambda mac: recoveries.append(mac),
            ),
            0,
        )
        # 1 startup pass + 2 matching events (both past cooldown)
        self.assertEqual(recoveries, ["68:52:10:35:29:44"] * 3)

    def test_sets_default_sink_by_name(self):
        calls = []

        def run(argv):
            calls.append(argv)
            return CompletedProcess(argv, 0, "", "")

        self.assertTrue(set_default_sink("bluez_output.test.1", run=run))
        self.assertEqual(calls, [["pactl", "set-default-sink", "bluez_output.test.1"]])


if __name__ == "__main__":
    unittest.main()
