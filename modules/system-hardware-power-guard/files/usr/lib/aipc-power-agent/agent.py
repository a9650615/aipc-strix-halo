#!/usr/bin/env python3
"""aipc-power-agent — one host daemon, two orthogonal power policies.

Policies (shared poll loop only; decisions never merged):
  - backfeed: weak-AC battery back-feed clamp + charge-cap persistence
  - core_parking: offline half CPUs when user selects power-saver (PPD)

Replaces:
  - power-guard.service  (/usr/lib/aipc-power-guard/power_guard.py)
  - aipc-usbc-core-policy.service  (/usr/local/sbin/aipc-usbc-core-policy.py)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

# Allow `python3 /usr/lib/aipc-power-agent/agent.py` without package install.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from backfeed import BackfeedGuard  # noqa: E402
from core_parking import CoreParking  # noqa: E402

LOG = logging.getLogger("aipc-power-agent")

DEFAULT_CONFIG = "/etc/aipc/power-agent/config.yaml"
LEGACY_CONFIG = "/etc/aipc/power-guard/config.yaml"
DEFAULT_STATE = "/var/lib/aipc-power-agent/state.json"
LEGACY_STATE = "/var/lib/aipc-power-guard/state.json"
AGENT_DISABLE_SENTINEL = "/etc/aipc/power-agent.disabled"


def load_config(path: str | None = None) -> dict:
    candidates = []
    if path:
        candidates.append(path)
    env = os.environ.get("AIPC_POWER_AGENT_CONFIG") or os.environ.get("POWER_GUARD_CONFIG")
    if env:
        candidates.append(env)
    candidates.extend([DEFAULT_CONFIG, LEGACY_CONFIG])

    raw: dict = {}
    chosen = None
    for p in candidates:
        try:
            import yaml

            with open(p) as f:
                raw = yaml.safe_load(f) or {}
            chosen = p
            break
        except FileNotFoundError:
            continue
        except ImportError:
            LOG.warning("PyYAML missing — using defaults")
            break
        except Exception as e:  # noqa: BLE001
            LOG.error("config load failed %s: %s", p, e)
            break

    if chosen:
        LOG.info("loaded config from %s", chosen)
    else:
        LOG.warning("no config found — using defaults")

    return normalize_config(raw)


def normalize_config(raw: dict) -> dict:
    """Accept new nested shape or legacy flat power-guard keys."""
    poll = float(raw.get("poll_interval_s", 3))
    state_file = raw.get("state_file") or DEFAULT_STATE

    if "backfeed" in raw or "core_parking" in raw:
        backfeed = dict(raw.get("backfeed") or {})
        core = dict(raw.get("core_parking") or {})
    else:
        # Legacy flat config: everything is backfeed; core_parking defaults on.
        backfeed = {k: v for k, v in raw.items() if k not in ("poll_interval_s", "log_level")}
        core = {}

    backfeed.setdefault("enabled", True)
    core.setdefault("enabled", True)
    backfeed.setdefault("state_file", state_file)
    # Prefer new state dir even when loading legacy config.
    if backfeed.get("state_file") == LEGACY_STATE:
        backfeed["state_file"] = DEFAULT_STATE

    return {
        "poll_interval_s": poll,
        "log_level": raw.get("log_level") or os.environ.get("AIPC_POWER_AGENT_LOG")
        or os.environ.get("POWER_GUARD_LOG")
        or "INFO",
        "state_file": backfeed.get("state_file", DEFAULT_STATE),
        "agent_disable_sentinel": raw.get("agent_disable_sentinel", AGENT_DISABLE_SENTINEL),
        "backfeed": backfeed,
        "core_parking": core,
    }


def persist_state(path: str, payload: dict) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload))
        # Mirror legacy path so old `aipc power-guard status` still works.
        if path != LEGACY_STATE:
            try:
                Path(LEGACY_STATE).parent.mkdir(parents=True, exist_ok=True)
                Path(LEGACY_STATE).write_text(json.dumps(payload.get("backfeed") or payload))
            except OSError:
                pass
    except OSError as e:
        LOG.debug("state persist failed: %s", e)


def self_test() -> int:
    import glob

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
    if probs:
        print("aipc-power-agent self-test FAIL: " + "; ".join(probs), file=sys.stderr)
        return 1
    from backfeed import _read, _read_int

    print(
        f"aipc-power-agent self-test OK: {len(cpus)} cpus, "
        f"AC online={_read_int(ac)}, BAT status={_read(f'{bat}/status')}, "
        f"power_now={_read_int(f'{bat}/power_now')}"
    )
    return 0


class PowerAgent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.poll_interval = float(cfg["poll_interval_s"])
        self.state_file = cfg["state_file"]
        self.agent_sentinel = cfg["agent_disable_sentinel"]
        self.policies: list = []

        bf_cfg = cfg["backfeed"]
        if bf_cfg.get("enabled", True):
            self.policies.append(("backfeed", BackfeedGuard(bf_cfg)))

        cp_cfg = cfg["core_parking"]
        if cp_cfg.get("enabled", True):
            self.policies.append(("core_parking", CoreParking(cp_cfg)))

    def run(self) -> None:
        LOG.info(
            "aipc-power-agent starting: policies=%s poll=%ss",
            [n for n, _ in self.policies],
            self.poll_interval,
        )
        for _name, policy in self.policies:
            policy.start()

        def _on_stop(signum, _frame):
            LOG.warning("signal %s — shutting down policies", signum)
            for _n, policy in self.policies:
                try:
                    policy.shutdown()
                except Exception as e:  # noqa: BLE001
                    LOG.error("shutdown %s: %s", _n, e)
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, _on_stop)
        signal.signal(signal.SIGINT, _on_stop)

        while True:
            try:
                self.step()
            except Exception as e:  # noqa: BLE001
                LOG.error("step error: %s", e)
            time.sleep(self.poll_interval)

    def step(self) -> None:
        if os.path.exists(self.agent_sentinel):
            LOG.debug("agent kill switch active — monitoring only")
            return

        combined: dict = {"ts": time.time(), "policies": {}}
        for name, policy in self.policies:
            snap = policy.step()
            if snap is not None:
                combined["policies"][name] = snap
                if name == "backfeed":
                    # Flatten backfeed fields for legacy status readers.
                    for k, v in snap.items():
                        if k != "policy":
                            combined[k] = v
        persist_state(self.state_file, combined)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return self_test()

    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, str(cfg["log_level"]).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    PowerAgent(cfg).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
