#!/usr/bin/env python3
"""AIPC hardware power guard — prevents battery back-feed drain on weak AC.

When the SoC draws more than the AC adapter can supply, the battery back-feeds
to cover the gap (status flips to Discharging while AC0 is online, or power_now
goes negative). Sustained back-feed degrades the battery. This guard clamps CPU
frequency + EPP to cap system draw, then releases adaptively once the supply
margin recovers.

Runs on host (not a container): it writes sysfs cpufreq nodes that need root.

Controls (AMD Ryzen AI MAX+ 395, amd-pstate-epp):
  - scaling_max_freq      : hard ceiling on core frequency (kHz)
  - energy_performance_preference : amd-pstate EPP hint (power .. performance)

Detection (two signals, both read from /sys/class/power_supply):
  - status == Discharging AND AC0 online == 1   -> definite back-feed
  - power_now < drain_threshold_uw              -> early numeric back-feed
  - power_now trending down toward 0 while charging -> caution (approaching limit)

KILL SWITCH: touch /etc/aipc/power-guard.disabled to freeze (monitor-only).
OBSERVE-ONLY: dry_run: true logs would-act decisions but writes nothing.

Spec: openspec/changes/power-guard-hardware-limit/
"""

from __future__ import annotations

import glob
import json
import logging
import os
import signal
import time
from pathlib import Path

DEFAULT_DISABLE_SENTINEL = "/etc/aipc/power-guard.disabled"
DEFAULT_STATE_FILE = "/var/lib/aipc-power-guard/state.json"
DEFAULT_CONFIG = "/etc/aipc/power-guard/config.yaml"

LOG = logging.getLogger("power-guard")


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


class PowerGuard:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.ac_online_path = cfg.get("ac_online_path", "/sys/class/power_supply/AC0/online")
        self.bat_path = cfg.get("bat_path", "/sys/class/power_supply/BAT0")
        self.cpu_paths = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq"))
        self.epp_avail = self._epp_choices()

        # thresholds / timing
        self.drain_threshold_uw = int(cfg.get("drain_threshold_uw", -1_000_000))  # -1W
        self.observe_period_s = int(cfg.get("reconnect_observe_period_s", 30))
        self.poll_interval = float(cfg.get("poll_interval_s", 3))
        self.expand_step = float(cfg.get("expand_step", 0.10))
        self.dry_run = bool(cfg.get("dry_run", True))
        self.sentinel = cfg.get("disable_sentinel", DEFAULT_DISABLE_SENTINEL)
        self.state_file = cfg.get("state_file", DEFAULT_STATE_FILE)

        # clamp targets (fraction of original cpuinfo_max_freq)
        self.emergency_freq_factor = float(cfg.get("emergency_freq_factor", 0.45))
        self.reconnect_freq_factor = float(cfg.get("reconnect_freq_factor", 0.60))
        self.recover_freq_factor = float(cfg.get("recover_freq_factor", 0.80))

        # amd-pstate EPP per state
        self.epp_emergency = cfg.get("epp_emergency", "power")
        self.epp_normal = cfg.get("epp_normal", "default")

        # runtime
        self.state = "INIT"
        self.reconnect_t0 = 0.0
        self.cur_factor = 1.0
        self.orig_max_freq: dict[str, int] = {}
        self.orig_epp: str | None = None
        self.last_power: int | None = None

    # ---------- sysfs helpers ----------
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
        }

    def _capture_originals(self) -> None:
        if self.orig_max_freq:
            return
        for c in self.cpu_paths:
            mx = _read_int(f"{c}/cpuinfo_max_freq") or _read_int(f"{c}/scaling_max_freq")
            if mx:
                self.orig_max_freq[c] = mx
        self.orig_epp = _read(f"{self.cpu_paths[0]}/energy_performance_preference") if self.cpu_paths else None
        LOG.info("captured originals: %d cpus, max_freq sample=%s, epp=%s",
                 len(self.orig_max_freq),
                 next(iter(self.orig_max_freq.values()), None), self.orig_epp)

    # ---------- enforcers ----------
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
        """Restore original frequency + EPP."""
        if self.dry_run:
            LOG.info("[dry-run] would release (restore originals)")
            return
        self._capture_originals()
        okf = 0
        for c, mx in self.orig_max_freq.items():
            if _write(f"{c}/scaling_max_freq", mx):
                okf += 1
        LOG.info("released freq: restored %d/%d cpus", okf, len(self.orig_max_freq))
        # EPP intentionally NOT restored — tuned/powerdevil own it; we only
        # touch EPP during EMERGENCY/RECONNECTING and hand it back on release.

    # ---------- state ----------
    def _set_state(self, s: str) -> None:
        if s != self.state:
            LOG.warning("STATE %s -> %s", self.state, s)
            self.state = s

    def _persist(self, bat: dict) -> None:
        try:
            Path(self.state_file).parent.mkdir(parents=True, exist_ok=True)
            Path(self.state_file).write_text(json.dumps({
                "state": self.state,
                "ac_online": self._ac_online(),
                "bat_status": bat["status"],
                "power_now_uw": bat["power_now"],
                "capacity": bat["capacity"],
                "cur_factor": round(self.cur_factor, 3),
                "dry_run": self.dry_run,
                "ts": time.time(),
            }))
        except OSError as e:
            LOG.debug("state persist failed: %s", e)

    # ---------- charge threshold persistence ----------
    def _apply_charge_threshold(self) -> None:
        """Persist charge_control_end_threshold on boot (ASUS EC resets it to 100
        before login; KDE only re-sets it after the user session starts)."""
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
            LOG.info("set charge_control_end_threshold=%d (was %s) — persisting across reboot gap", pct, cur)

    # ---------- main loop ----------
    def step(self) -> None:
        if os.path.exists(self.sentinel):
            LOG.debug("kill switch active — monitoring only")
            return

        ac = self._ac_online()
        bat = self._bat()
        pnow = bat["power_now"]
        draining = (bat["status"] == "Discharging" and ac) or \
                   (pnow is not None and pnow < self.drain_threshold_uw)
        delta = (pnow - self.last_power) if (pnow is not None and self.last_power is not None) else 0
        self.last_power = pnow

        # offline -> DISCHARGING, release any clamp (battery power is fine when unplugged)
        if not ac:
            if self.state not in ("DISCHARGING", "INIT"):
                self._release()
                self.cur_factor = 1.0
            self._set_state("DISCHARGING")
            self._persist(bat)
            return

        # online + definite drain -> EMERGENCY
        if draining:
            self._set_state("EMERGENCY")
            self._apply_freq(self.emergency_freq_factor)
            self._apply_epp(self.epp_emergency)
            self.cur_factor = self.emergency_freq_factor
            self._persist(bat)
            return

        # online + stable: observe before releasing. INIT (boot/restart) also
        # observes — at start we don't know which adapter is attached (65W vs
        # 140W), so confirm the margin first. Cost: a ~observe_period_s throttle
        # after every start. Accepted: a wrong guess here back-feeds the battery.
        if self.state in ("DISCHARGING", "INIT", "EMERGENCY"):
            self._set_state("RECONNECTING")
            self.reconnect_t0 = time.time()
            self._apply_freq(self.reconnect_freq_factor)
            self._apply_epp(self.epp_emergency)
            self.cur_factor = self.reconnect_freq_factor

        if self.state == "RECONNECTING":
            if time.time() - self.reconnect_t0 >= self.observe_period_s:
                # Stop touching EPP once stable: tuned/powerdevil own EPP outside
                # emergencies. Only scaling_max_freq (hard ceiling, which they do
                # NOT write) is ours — that's the clamp that actually bounds draw.
                # Writing EPP here would fight tuned every poll.
                self._set_state("EXPANDING")
        elif self.state == "EXPANDING":
            if delta < 0:  # margin shrinking
                self._set_state("CAUTIONARY")
            else:
                nf = min(1.0, self.cur_factor + self.expand_step)
                if nf > self.cur_factor:
                    self.cur_factor = nf
                    self._apply_freq(nf)
        elif self.state == "CAUTIONARY":
            if delta > 0:
                self._set_state("EXPANDING")

        self._persist(bat)

    def run(self) -> None:
        LOG.info("power-guard started: dry_run=%s cpus=%d epp=%s",
                 self.dry_run, len(self.cpu_paths), self.epp_avail)
        self._capture_originals()
        self._apply_charge_threshold()

        # Release clamps on stop so we never leave the box throttled.
        def _on_stop(signum, _frame):
            LOG.warning("signal %s — releasing clamps before exit", signum)
            if self.state in ("EMERGENCY", "RECONNECTING", "CAUTIONARY", "EXPANDING"):
                self._release()
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, _on_stop)
        signal.signal(signal.SIGINT, _on_stop)

        while True:
            try:
                self.step()
            except Exception as e:  # never die on a bad poll
                LOG.error("step error: %s", e)
            time.sleep(self.poll_interval)


def self_test() -> int:
    """Static + live-read checks. Exit 0 ok, non-zero with stderr diagnosis."""
    import sys
    bat = "/sys/class/power_supply/BAT0"
    ac = "/sys/class/power_supply/AC0/online"
    probs = []
    if not os.path.isdir(bat):
        probs.append(f"missing {bat}")
    if not os.path.exists(ac):
        probs.append(f"missing {ac}")
    cpus = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq")
    if not cpus:
        probs.append("no cpufreq nodes")
    else:
        drv = _read(f"{cpus[0]}/scaling_driver")
        if drv != "amd-pstate-epp":
            print(f"warn: scaling_driver={drv} (tuned for amd-pstate-epp)", file=sys.stderr)
    if probs:
        print("power-guard self-test FAIL: " + "; ".join(probs), file=sys.stderr)
        return 1
    print(f"power-guard self-test OK: {len(cpus)} cpus, "
          f"AC online={_read_int(ac)}, BAT status={_read(f'{bat}/status')}, "
          f"power_now={_read_int(f'{bat}/power_now')}")
    return 0


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=os.environ.get("POWER_GUARD_LOG", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    cfg_path = os.environ.get("POWER_GUARD_CONFIG", DEFAULT_CONFIG)
    try:
        import yaml
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"config not found: {cfg_path} — using defaults", file=sys.stderr)
        cfg = {}
    except ImportError:
        print("PyYAML missing — using defaults", file=sys.stderr)
        cfg = {}
    PowerGuard(cfg).run()
