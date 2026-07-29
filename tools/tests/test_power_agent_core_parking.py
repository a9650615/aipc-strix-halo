import importlib.util
from pathlib import Path


def load_core_parking():
    path = (
        Path(__file__).resolve().parents[2]
        / "modules/system-hardware-power-guard/files/usr/lib/aipc-power-agent/core_parking.py"
    )
    spec = importlib.util.spec_from_file_location("core_parking", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_agent():
    path = (
        Path(__file__).resolve().parents[2]
        / "modules/system-hardware-power-guard/files/usr/lib/aipc-power-agent/agent.py"
    )
    spec = importlib.util.spec_from_file_location("power_agent", path)
    module = importlib.util.module_from_spec(spec)
    # agent.py inserts its dir on import path via run; load backfeed first is via sys.path
    import sys

    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(module)
    return module


def test_powersave_wanted_follows_ppd(monkeypatch):
    mod = load_core_parking()
    policy = mod.CoreParking({"debounce_polls": 1, "dry_run": True})
    policy._topology_ok = True

    monkeypatch.setattr(mod.CoreParking, "ppd_active_profile", staticmethod(lambda: "power-saver"))
    want, reason = policy.powersave_wanted()
    assert want is True
    assert "power-saver" in reason

    monkeypatch.setattr(mod.CoreParking, "ppd_active_profile", staticmethod(lambda: "balanced"))
    want, reason = policy.powersave_wanted()
    assert want is False


def test_core_parking_debounces_then_parks(monkeypatch):
    mod = load_core_parking()
    policy = mod.CoreParking({"debounce_polls": 2, "dry_run": True})
    policy._topology_ok = True
    calls = []

    monkeypatch.setattr(policy, "powersave_wanted", lambda: (True, "ppd=power-saver"))
    monkeypatch.setattr(policy, "offline_half", lambda reason: calls.append(("off", reason)))
    monkeypatch.setattr(policy, "restore_all", lambda reason: calls.append(("on", reason)))
    monkeypatch.setattr(policy, "open_minimum_frequency", lambda: None)

    policy.step()
    assert calls == []  # not yet debounced
    policy.step()
    assert calls == [("off", "ppd=power-saver")]
    assert policy.applied is True


def test_normalize_config_legacy_flat():
    agent = load_agent()
    cfg = agent.normalize_config(
        {
            "dry_run": True,
            "poll_interval_s": 5,
            "charge_threshold_percent": 80,
        }
    )
    assert cfg["poll_interval_s"] == 5.0
    assert cfg["backfeed"]["enabled"] is True
    assert cfg["backfeed"]["dry_run"] is True
    assert cfg["backfeed"]["charge_threshold_percent"] == 80
    assert cfg["core_parking"]["enabled"] is True


def test_normalize_config_nested():
    agent = load_agent()
    cfg = agent.normalize_config(
        {
            "poll_interval_s": 3,
            "backfeed": {"enabled": False, "dry_run": False},
            "core_parking": {"enabled": True, "debounce_polls": 4},
        }
    )
    assert cfg["backfeed"]["enabled"] is False
    assert cfg["core_parking"]["debounce_polls"] == 4
