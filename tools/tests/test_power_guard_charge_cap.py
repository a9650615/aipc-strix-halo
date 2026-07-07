import importlib.util
import time
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[2] / "modules/system-hardware-power-guard/files/usr/lib/aipc-power-guard/power_guard.py"
    spec = importlib.util.spec_from_file_location("power_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_not_charging_at_charge_cap_is_not_emergency(monkeypatch, tmp_path):
    module = load_module()
    guard = module.PowerGuard({"dry_run": True, "state_file": str(tmp_path / "state.json")})
    guard.cpu_paths = []
    guard.epp_avail = []

    monkeypatch.setattr(guard, "_ac_online", lambda: True)
    monkeypatch.setattr(guard, "_bat", lambda: {
        "status": "Not charging",
        "power_now": 0,
        "capacity": 85,
        "energy_now": 1_000_000,
    })

    guard.step()

    assert guard.state == "RECONNECTING"
    assert guard.cur_factor == guard.reconnect_freq_factor


def test_reconnecting_restores_epp_before_expanding(monkeypatch, tmp_path):
    module = load_module()
    guard = module.PowerGuard({
        "dry_run": False,
        "state_file": str(tmp_path / "state.json"),
        "reconnect_observe_period_s": 0,
    })
    guard.cpu_paths = []
    guard.epp_avail = ["default", "power"]
    seen = []

    monkeypatch.setattr(guard, "_ac_online", lambda: True)
    monkeypatch.setattr(guard, "_bat", lambda: {
        "status": "Not charging",
        "power_now": 0,
        "capacity": 85,
        "energy_now": 1_000_000,
    })
    monkeypatch.setattr(guard, "_apply_freq", lambda factor: None)
    monkeypatch.setattr(guard, "_apply_epp", lambda epp: seen.append(epp))
    monkeypatch.setattr(time, "time", lambda: 1000)

    guard.step()
    guard.step()

    assert guard.state == "EXPANDING"
    assert seen == ["power", "default"]
