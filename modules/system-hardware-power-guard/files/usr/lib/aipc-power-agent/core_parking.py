#!/usr/bin/env python3
"""Core-parking policy — offline half the CPUs only in power-saver mode.

Follows tuned-ppd ActiveProfile (user intent). ASUS platform_profile is a
fallback only when PPD is unavailable. Orthogonal to back-feed clamping.

Absorbs the former aipc-usbc-core-policy daemon (name was legacy; it no longer
keys off USB-C PD).
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

LOG = logging.getLogger("aipc-power-agent.core_parking")

CPU_ROOT = Path("/sys/devices/system/cpu")
POLICY_ROOT = Path("/sys/devices/system/cpu/cpufreq")
PLATFORM_PROFILE = Path("/sys/firmware/acpi/platform_profile")
DEFAULT_DISABLE_SENTINEL = "/etc/aipc/power-agent/core-parking.disabled"


class CoreParking:
    """Park physical cores 8–15 (+ SMT siblings) when PPD is power-saver."""

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.debounce_polls = int(cfg.get("debounce_polls", 2))
        self.sentinel = Path(cfg.get("disable_sentinel", DEFAULT_DISABLE_SENTINEL))
        park_lo = int(cfg.get("park_core_lo", 8))
        park_hi = int(cfg.get("park_core_hi", 15))
        smt_offset = int(cfg.get("smt_offset", 16))
        self.pairs = [(i, i + smt_offset) for i in range(park_lo, park_hi + 1)]
        self.dry_run = bool(cfg.get("dry_run", False))

        self.applied: bool | None = None
        self.observed: bool | None = None
        self.stable = 0
        self.last_reason = ""
        self._topology_ok = False
        self._last_error: str | None = None

    def _disabled(self) -> bool:
        return self.sentinel.exists()

    def start(self) -> None:
        try:
            self._validate_topology()
            self._topology_ok = True
            LOG.info(
                "core_parking policy started: pairs=%s dry_run=%s",
                self.pairs,
                self.dry_run,
            )
        except (RuntimeError, FileNotFoundError, OSError) as e:
            self._topology_ok = False
            self._last_error = str(e)
            LOG.error("core_parking topology validation failed: %s — policy inert", e)

    def _validate_topology(self) -> None:
        expected = {lo: {lo, hi} for lo, hi in self.pairs}
        expected.update({hi: {lo, hi} for lo, hi in self.pairs})
        for cpu, siblings in expected.items():
            path = CPU_ROOT / f"cpu{cpu}" / "topology" / "thread_siblings_list"
            if not path.exists():
                raise RuntimeError(f"missing topology for cpu{cpu}")
            values = {int(x) for x in path.read_text().strip().replace("-", ",").split(",") if x}
            if values != siblings:
                raise RuntimeError(f"unexpected sibling topology cpu{cpu}: {values} != {siblings}")

    @staticmethod
    def ppd_active_profile() -> str | None:
        try:
            out = subprocess.check_output(
                [
                    "busctl",
                    "get-property",
                    "org.freedesktop.UPower.PowerProfiles",
                    "/org/freedesktop/UPower/PowerProfiles",
                    "org.freedesktop.UPower.PowerProfiles",
                    "ActiveProfile",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).strip()
            return out.split('"', 2)[1] if out.startswith("s ") else None
        except (subprocess.SubprocessError, FileNotFoundError, IndexError, OSError):
            return None

    def powersave_wanted(self) -> tuple[bool, str]:
        ppd = self.ppd_active_profile()
        if ppd is not None:
            return ppd == "power-saver", f"ppd={ppd}"
        try:
            profile = PLATFORM_PROFILE.read_text().strip()
        except (FileNotFoundError, OSError):
            profile = "unknown"
        return profile == "quiet", f"platform_profile={profile} (ppd unavailable)"

    def _cpu_online_path(self, cpu: int) -> Path:
        return CPU_ROOT / f"cpu{cpu}" / "online"

    def _write_cpu(self, cpu: int, value: str) -> None:
        path = self._cpu_online_path(cpu)
        if not path.exists():
            return
        try:
            if path.read_text().strip() != value:
                if self.dry_run:
                    LOG.info("[dry-run] would set cpu%d online=%s", cpu, value)
                    return
                path.write_text(value)
        except OSError as exc:
            LOG.warning("cpu%d online=%s failed: %s", cpu, value, exc)

    def offline_half(self, reason: str) -> None:
        for _lo, hi in self.pairs:
            self._write_cpu(hi, "0")
        for lo, _hi in self.pairs:
            self._write_cpu(lo, "0")
        LOG.warning(
            "powersave core-lock ON (%s): offlined park pairs %s",
            reason,
            self.pairs,
        )

    def restore_all(self, reason: str) -> None:
        for lo, _hi in self.pairs:
            self._write_cpu(lo, "1")
        for _lo, hi in self.pairs:
            self._write_cpu(hi, "1")
        LOG.info("powersave core-lock OFF (%s): restored targeted CPUs", reason)

    def open_minimum_frequency(self) -> None:
        """Expose firmware floor without touching dynamic maximum."""
        changed = 0
        for policy in sorted(POLICY_ROOT.glob("policy*")):
            floor_path = policy / "cpuinfo_min_freq"
            minimum_path = policy / "scaling_min_freq"
            try:
                floor = floor_path.read_text().strip()
                if minimum_path.read_text().strip() != floor:
                    if self.dry_run:
                        LOG.info("[dry-run] would set %s = %s", minimum_path, floor)
                    else:
                        minimum_path.write_text(floor)
                    changed += 1
            except (FileNotFoundError, OSError):
                continue
        if changed:
            LOG.info(
                "opened CPU minimum frequency to firmware floor for %d policies",
                changed,
            )

    def step(self) -> dict | None:
        if not self._topology_ok:
            return {
                "policy": "core_parking",
                "error": self._last_error or "topology not validated",
                "applied": self.applied,
                "ts": time.time(),
            }
        if self._disabled():
            if self.applied:
                self.restore_all("core-parking kill switch")
                self.applied = False
            return {
                "policy": "core_parking",
                "disabled": True,
                "applied": False,
                "ts": time.time(),
            }

        want_lock, reason = self.powersave_wanted()
        if want_lock == self.observed and reason == self.last_reason:
            self.stable += 1
        else:
            self.observed = want_lock
            self.last_reason = reason
            self.stable = 1

        if self.stable >= self.debounce_polls and want_lock != self.applied:
            if want_lock:
                self.offline_half(reason)
            else:
                self.restore_all(reason)
            self.applied = want_lock

        self.open_minimum_frequency()
        return {
            "policy": "core_parking",
            "want_lock": want_lock,
            "reason": reason,
            "applied": self.applied,
            "stable": self.stable,
            "disabled": False,
            "ts": time.time(),
        }

    def shutdown(self) -> None:
        if self._topology_ok and self.applied:
            self.restore_all("shutdown")
            self.applied = False
        elif self._topology_ok:
            # Always restore on stop so a previous crash/park cannot stick.
            self.restore_all("shutdown")
        self.open_minimum_frequency()

    def snapshot(self) -> dict:
        return {
            "policy": "core_parking",
            "applied": self.applied,
            "reason": self.last_reason,
            "disabled": self._disabled(),
            "topology_ok": self._topology_ok,
            "ts": time.time(),
        }
