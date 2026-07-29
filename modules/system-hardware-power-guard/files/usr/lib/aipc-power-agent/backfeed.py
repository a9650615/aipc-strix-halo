#!/usr/bin/env python3
"""Back-feed guard policy — clamp CPU when weak AC forces battery drain.

Orthogonal to core parking: this reacts to hardware supply events, not the
user's power-saver preference. Shared only via the aipc-power-agent poll loop.

Spec lineage: openspec/changes/power-guard-hardware-limit/
"""

from __future__ import annotations

import glob
import json
import logging
import os
import time
from pathlib import Path

LOG = logging.getLogger("aipc-power-agent.backfeed")

DEFAULT_DISABLE_SENTINEL = "/etc/aipc/power-agent/backfeed.disabled"
LEGACY_DISABLE_SENTINEL = "/etc/aipc/power-guard.disabled"
DEFAULT_STATE_FILE = "/var/lib/aipc-power-agent/state.json"


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _read_int(path: str) -> int | None:
    v = _read(path)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def _write(path: str, value) -> bool:
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except (PermissionError, OSError) as e:
        LOG.error("write failed %s=%s: %s", path, value, e)
        return False


class BackfeedGuard:
    """Battery back-feed clamp + charge-cap persistence."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.ac_online_path = cfg.get("ac_online_path", "/sys/class/power_supply/AC0/online")
        self.bat_path = cfg.get("bat_path", "/sys/class/power_supply/BAT0")
        self.cpu_paths = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq"))
        self.epp_avail = self._epp_choices()

        self.drain_threshold_uw = int(cfg.get("drain_threshold_uw", -1_000_000))
        self.observe_period_s = int(cfg.get("reconnect_observe_period_s", 30))
        self.expand_step = float(cfg.get("expand_step", 0.10))
        self.dry_run = bool(cfg.get("dry_run", True))
        self.sentinel = cfg.get("disable_sentinel", DEFAULT_DISABLE_SENTINEL)
        self.legacy_sentinel = cfg.get("legacy_disable_sentinel", LEGACY_DISABLE_SENTINEL)
        self.state_file = cfg.get("state_file", DEFAULT_STATE_FILE)

        self.emergency_freq_factor = float(cfg.get("emergency_freq_factor", 0.45))
        self.reconnect_freq_factor = float(cfg.get("reconnect_freq_factor", 0.60))
        self.recover_freq_factor = float(cfg.get("recover_freq_factor", 0.80))

        self.epp_emergency = cfg.get("epp_emergency", "power")
        self.epp_normal = cfg.get("epp_normal", "default")

        self.state = "INIT"
        self.reconnect_t0 = 0.0
        self.cur_factor = 1.0
        self.orig_max_freq: dict[str, int] = {}
        self.orig_epp: str | None = None
        self.last_power: int | None = None
        self.last_energy: int | None = None
        self.energy_drop_streak = 0
        self._started = False

    def _disabled(self) -> bool:
        return os.path.exists(self.sentinel) or os.path.exists(self.legacy_sentinel)

    def _epp_choices(self) -> list[str]:
        v = _read("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_available_preferences")
        return v.split() if v else []

    def _ac_online(self) -> bool:
        return _read_int(self.ac_online_path) == 1

    def _bat(self) -> dict:
        return {
            "status": _read(f"{self.bat_path}/status") or "Unknown",
            "power_now": _read_int(f"{self.bat_path}/power_now"),
            "capacity": _read_int(f"{self.bat_path}/capacity"),
            "energy_now": _read_int(f"{self.bat_path}/energy_now"),
        }

    def _capture_originals(self) -> None:
        if self.orig_max_freq:
            return
        for c in self.cpu_paths:
            mx = _read_int(f"{c}/cpuinfo_max_freq") or _read_int(f"{c}/scaling_max_freq")
            if mx:
                self.orig_max_freq[c] = mx
        self.orig_epp = (
            _read(f"{self.cpu_paths[0]}/energy_performance_preference") if self.cpu_paths else None
        )
        LOG.info(
            "captured originals: %d cpus, max_freq sample=%s, epp=%s",
            len(self.orig_max_freq),
            next(iter(self.orig_max_freq.values()), None),
            self.orig_epp,
        )

    def _apply_freq(self, factor: float) -> None:
        if self.dry_run:
            LOG.info("[dry-run] would set scaling_max_freq *= %.2f", factor)
            return
        self._capture_originals()
        ok = 0
        for c, mx in self.orig_max_freq.items():
            if _write(f"{c}/scaling_max_freq", int(mx * factor)):
                ok += 1
        LOG.info("applied freq factor %.2f on %d/%d cpus", factor, ok, len(self.orig_max_freq))

    def _apply_epp(self, epp: str) -> None:
        if epp not in self.epp_avail:
            LOG.warning("epp %r not in available %s — skipping", epp, self.epp_avail)
            return
        if self.dry_run:
            LOG.info("[dry-run] would set EPP=%s", epp)
            return
        ok = 0
        for c in self.cpu_paths:
            if _write(f"{c}/energy_performance_preference", epp):
                ok += 1
        LOG.info("applied EPP=%s on %d/%d cpus", epp, ok, len(self.cpu_paths))

    def _release(self) -> None:
        if self.dry_run:
            LOG.info("[dry-run] would release (restore originals)")
            return
        self._capture_originals()
        okf = 0
        for c, mx in self.orig_max_freq.items():
            if _write(f"{c}/scaling_max_freq", mx):
                okf += 1
        LOG.info("released freq: restored %d/%d cpus", okf, len(self.orig_max_freq))

    def _set_state(self, s: str) -> None:
        if s != self.state:
            LOG.warning("STATE %s -> %s", self.state, s)
            self.state = s

    def snapshot(self, bat: dict | None = None) -> dict:
        bat = bat or self._bat()
        return {
            "policy": "backfeed",
            "state": self.state,
            "ac_online": self._ac_online(),
            "bat_status": bat["status"],
            "power_now_uw": bat["power_now"],
            "capacity": bat["capacity"],
            "cur_factor": round(self.cur_factor, 3),
            "dry_run": self.dry_run,
            "disabled": self._disabled(),
            "ts": time.time(),
        }

    def _persist_partial(self, bat: dict) -> dict:
        return self.snapshot(bat)

    def _apply_charge_threshold(self) -> None:
        pct = self.cfg.get("charge_threshold_percent")
        if not pct:
            return
        path = f"{self.bat_path}/charge_control_end_threshold"
        cur = _read_int(path)
        if cur == int(pct):
            return
        if self.dry_run:
            LOG.info("[dry-run] would set charge threshold %d%% (cur %s)", pct, cur)
            return
        if _write(path, int(pct)):
            LOG.info(
                "set charge_control_end_threshold=%d (was %s) — persisting across reboot gap",
                pct,
                cur,
            )

    def start(self) -> None:
        if self._started:
            return
        LOG.info(
            "backfeed policy started: dry_run=%s cpus=%d epp=%s",
            self.dry_run,
            len(self.cpu_paths),
            self.epp_avail,
        )
        self._capture_originals()
        self._apply_charge_threshold()
        self._started = True

    def step(self) -> dict | None:
        """One poll. Returns a state snapshot for the agent to persist."""
        if not self._started:
            self.start()
        if self._disabled():
            LOG.debug("backfeed kill switch active — monitoring only")
            return self.snapshot()

        ac = self._ac_online()
        bat = self._bat()
        pnow = bat["power_now"]
        enow = bat["energy_now"]

        if enow is not None and self.last_energy is not None and ac:
            self.energy_drop_streak = self.energy_drop_streak + 1 if enow < self.last_energy else 0
        else:
            self.energy_drop_streak = 0
        self.last_energy = enow

        draining = (
            (bat["status"] == "Discharging" and ac)
            or (pnow is not None and pnow < self.drain_threshold_uw)
            or self.energy_drop_streak >= 2
        )
        delta = (pnow - self.last_power) if (pnow is not None and self.last_power is not None) else 0
        self.last_power = pnow

        if not ac:
            if self.state not in ("DISCHARGING", "INIT"):
                self._release()
                self.cur_factor = 1.0
            self._set_state("DISCHARGING")
            return self.snapshot(bat)

        if draining:
            self._set_state("EMERGENCY")
            self._apply_freq(self.emergency_freq_factor)
            self._apply_epp(self.epp_emergency)
            self.cur_factor = self.emergency_freq_factor
            return self.snapshot(bat)

        if self.state in ("DISCHARGING", "INIT", "EMERGENCY"):
            self._set_state("RECONNECTING")
            self.reconnect_t0 = time.time()
            self._apply_freq(self.reconnect_freq_factor)
            self._apply_epp(self.epp_emergency)
            self.cur_factor = self.reconnect_freq_factor

        if self.state == "RECONNECTING":
            if time.time() - self.reconnect_t0 >= self.observe_period_s:
                self._apply_epp(self.epp_normal)
                self._set_state("EXPANDING")
        elif self.state == "EXPANDING":
            if delta < 0:
                self._set_state("CAUTIONARY")
            else:
                nf = min(1.0, self.cur_factor + self.expand_step)
                if nf > self.cur_factor:
                    self.cur_factor = nf
                    self._apply_freq(nf)
        elif self.state == "CAUTIONARY":
            if delta > 0:
                self._set_state("EXPANDING")

        return self.snapshot(bat)

    def shutdown(self) -> None:
        if self.state in ("EMERGENCY", "RECONNECTING", "CAUTIONARY", "EXPANDING"):
            LOG.warning("backfeed shutdown — releasing clamps")
            self._release()


# Backward-compatible name for existing tests / call sites.
PowerGuard = BackfeedGuard
