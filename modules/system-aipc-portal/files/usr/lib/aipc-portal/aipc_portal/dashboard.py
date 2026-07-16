from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from aipc_portal.ops import service_can_start, service_display_state, service_group
from aipc_portal.registry import ServiceStatus, load_automation, load_services, probe_all

DEVICE_STATE = Path("/run/aipc/command-center.json")
NPU_DEVICE = Path("/dev/accel/accel0")
TYPEC_ROOT = Path("/sys/class/typec")
PLATFORM_PROFILE = Path("/sys/firmware/acpi/platform_profile")
# Full Lemonade /api/v0/health is expensive and can block the inference loop
# under thrash. Prefer short timeouts + cache; never fan out heavy probes.
LEMONADE_HEALTH = "http://127.0.0.1:8001/api/v0/health"
OLLAMA_MODELS = "http://127.0.0.1:11434/api/ps"
PROBE_TIMEOUT_S = 0.4
SNAPSHOT_CACHE_S = 2.5

_snapshot_lock = threading.Lock()
_snapshot_cache: dict[str, object] | None = None
_snapshot_cache_at = 0.0


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return int(raw.split()[0])
    except (ValueError, IndexError):
        return None


def _bytes_to_gib(n: int | None) -> float | None:
    if n is None:
        return None
    return round(n / (1024**3), 1)


def _meminfo() -> dict[str, float | None]:
    total = available = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                available = int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return {
        "mem_total_gb": _bytes_to_gib(total),
        "mem_available_gb": _bytes_to_gib(available),
    }


def _gtt_info() -> dict[str, float | None]:
    used = total = None
    for card in ("card1", "card0"):
        base = Path(f"/sys/class/drm/{card}/device")
        u = _read_int(base / "mem_info_gtt_used")
        t = _read_int(base / "mem_info_gtt_total")
        if u is not None or t is not None:
            used, total = u, t
            break
    return {"gtt_used_gb": _bytes_to_gib(used), "gtt_total_gb": _bytes_to_gib(total)}


def _cpu_label() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                name = line.split(":", 1)[1].strip()
                # Compact: "AMD RYZEN AI MAX+ 395 w/ Radeon 8060S" → keep useful core
                if "MAX+" in name.upper() or "395" in name:
                    return "Ryzen AI MAX+ 395"
                return name[:48]
    except OSError:
        pass
    return "AI MAX+ 395"


def _os_release() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k] = v.strip().strip('"')
    except OSError:
        pass
    return out


def _hostname() -> str | None:
    for path in (Path("/etc/hostname"), Path("/proc/sys/kernel/hostname")):
        raw = _read_text(path)
        if raw:
            return raw.splitlines()[0].strip() or None
    return None


def _kernel_release() -> str | None:
    try:
        # uname -r equivalent without subprocess
        return Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def platform_snapshot() -> dict[str, object]:
    mem = _meminfo()
    gtt = _gtt_info()
    profile = _read_text(PLATFORM_PROFILE) or "unknown"
    choices_raw = _read_text(Path("/sys/firmware/acpi/platform_profile_choices")) or ""
    profile_choices = [c for c in choices_raw.split() if c]
    cpu = _cpu_label()
    osr = _os_release()
    host = _hostname()
    kernel = _kernel_release()
    parts: list[str] = []
    if mem["mem_available_gb"] is not None and mem["mem_total_gb"] is not None:
        parts.append(f"{mem['mem_available_gb']:.0f}/{mem['mem_total_gb']:.0f}G free")
    if gtt["gtt_used_gb"] is not None and gtt["gtt_total_gb"] is not None:
        parts.append(f"GTT {gtt['gtt_used_gb']:.1f}/{gtt['gtt_total_gb']:.0f}G")
    parts.append(f"profile {profile}")
    return {
        "availability": "available",
        "summary": " · ".join(parts),
        "cpu": cpu,
        "profile": profile,
        "profile_choices": profile_choices,
        "hostname": host,
        "os_name": osr.get("NAME") or osr.get("PRETTY_NAME"),
        "os_version": osr.get("VERSION") or osr.get("VERSION_ID"),
        "kernel": kernel,
        "chassis": "ROG Flow Z13 (GZ302 / Strix Halo)",
        **mem,
        **gtt,
    }


def _typec_active_role(raw: str) -> str:
    """Parse Type-C sysfs role lines like 'host [device]' → 'host'.

    Bracketed tokens are the *alternate* role, not the cable state.
    """
    text = (raw or "").strip().lower()
    if not text or text in {"[none]", "none"}:
        return ""
    # Drop bracketed alternatives, take first remaining token.
    cleaned = re.sub(r"\[[^\]]*\]", " ", text)
    parts = cleaned.split()
    return parts[0] if parts else ""


def _typec_partner_present(port: Path, root: Path) -> bool:
    """True only when a Type-C partner (cable/device) is registered.

    Presence of data_role=host alone is NOT a connection — dual-role ports
    always advertise a role. Partner nodes appear as portN-partner.
    """
    name = port.name  # port0
    candidates = (
        root / f"{name}-partner",
        port / f"{name}-partner",
        port / "partner",
    )
    for path in candidates:
        try:
            if path.exists():
                return True
        except OSError:
            continue
    try:
        if any(port.glob("*partner*")):
            return True
    except OSError:
        pass
    return False


def _typec_location(port: Path) -> dict[str, str | None]:
    loc = port / "physical_location"
    if not loc.is_dir():
        return {}
    out: dict[str, str | None] = {}
    for key in ("panel", "horizontal_position", "vertical_position", "dock"):
        out[key] = _read_text(loc / key)
    return out


def _usb_hub_maxchild(port_path: Path) -> int:
    """maxchild of the parent usbN root hub (0 if unknown)."""
    for parent in port_path.parents:
        name = parent.name
        if name.startswith("usb") and name[3:].isdigit() and (parent / "maxchild").is_file():
            raw = _read_text(parent / "maxchild")
            try:
                return int(raw) if raw else 0
            except ValueError:
                return 0
    return 0


def _usb_port_device(port_path: Path) -> dict[str, str | None]:
    dev = port_path / "device"
    if not (dev.exists() or dev.is_symlink()):
        return {}
    return {
        "product": _read_text(dev / "product"),
        "manufacturer": _read_text(dev / "manufacturer"),
        "id_vendor": _read_text(dev / "idVendor"),
        "id_product": _read_text(dev / "idProduct"),
    }


def usb_type_a_snapshot(sys_root: Path = Path("/sys")) -> dict[str, object]:
    """User-facing USB Type-A (and non-Type-C hotplug) ports.

    Kernel marks external connectors with connect_type=hotplug. Type-C dual-role
    USB companions typically sit on single-port root hubs (maxchild==1) in HS/SS
    pairs — those are covered by the Type-C card, so we exclude them here.
    Multi-port hubs (maxchild>1) host classic Type-A; HS+SS peers share location.
    """
    # Collect hotplug ports (dedupe by resolved path)
    found: list[Path] = []
    seen: set[str] = set()
    search_roots = [sys_root / "devices", sys_root / "bus" / "usb" / "devices"]
    for base in search_roots:
        if not base.is_dir():
            continue
        try:
            iterator = base.rglob("usb*-port*")
        except OSError:
            continue
        for path in iterator:
            if not path.is_dir():
                continue
            if not (path / "connect_type").is_file():
                continue
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            if (_read_text(path / "connect_type") or "").strip() != "hotplug":
                continue
            found.append(path)

    # Group by location (HS+SS companions share location); fall back to path.
    groups: dict[str, list[Path]] = {}
    for path in found:
        loc = (_read_text(path / "location") or "").strip() or str(path)
        groups.setdefault(loc, []).append(path)

    ports: list[dict[str, object]] = []
    for loc, members in sorted(groups.items(), key=lambda kv: kv[0]):
        maxchildren = [_usb_hub_maxchild(m) for m in members]
        # Single-port root hubs only → Type-C USB companion; skip.
        if maxchildren and all(m <= 1 for m in maxchildren):
            continue
        connected = False
        product = manufacturer = None
        state = None
        member_ids: list[str] = []
        for m in members:
            member_ids.append(m.name)
            st = _read_text(m / "state")
            if st:
                state = st
            info = _usb_port_device(m)
            if info:
                connected = True
                product = product or info.get("product")
                manufacturer = manufacturer or info.get("manufacturer")
        # Prefer human index by first member name
        label = members[0].name.replace("usb", "USB ").replace("-port", "-A/")
        ports.append(
            {
                "id": members[0].name,
                "label": label,
                "kind": "type-a",
                "state": "connected" if connected else "idle",
                "usb_state": state,
                "location": loc if not loc.startswith("/") else None,
                "members": member_ids,
                "product": product,
                "manufacturer": manufacturer,
                "partner": connected,
            }
        )

    connected_n = sum(1 for p in ports if p.get("state") == "connected")
    return {
        "availability": "available" if ports else "unavailable",
        "ports": ports,
        "ports_connected": connected_n,
        "ports_total": len(ports),
        "summary": (
            f"{connected_n}/{len(ports)} Type-A linked" if ports else "no Type-A ports"
        ),
    }


def io_snapshot(root: Path = TYPEC_ROOT) -> dict[str, object]:
    ports: list[dict[str, object]] = []
    if not root.is_dir():
        typec = {
            "availability": "unavailable",
            "ports": ports,
            "ports_connected": 0,
            "ports_total": 0,
            "summary": "no Type-C ports",
        }
    else:
        # Only top-level portN entries (not port0-partner as a "port")
        for port in sorted(p for p in root.glob("port*") if p.is_dir() and "-partner" not in p.name):
            raw_data = _read_text(port / "data_role") or ""
            raw_power = _read_text(port / "power_role") or ""
            connected = _typec_partner_present(port, root)
            loc = _typec_location(port)
            ports.append(
                {
                    "id": port.name,
                    "kind": "type-c",
                    "state": "connected" if connected else "idle",
                    "data_role": _typec_active_role(raw_data) or None,
                    "power_role": _typec_active_role(raw_power) or None,
                    "data_role_raw": raw_data.strip() or None,
                    "power_role_raw": raw_power.strip() or None,
                    "partner": connected,
                    "panel": loc.get("panel"),
                    "position": " ".join(
                        x
                        for x in (loc.get("horizontal_position"), loc.get("vertical_position"))
                        if x
                    )
                    or None,
                    "dock": loc.get("dock"),
                }
            )
        connected_n = sum(1 for p in ports if p.get("state") == "connected")
        typec = {
            "availability": "available" if ports else "unavailable",
            "ports": ports,
            "ports_connected": connected_n,
            "ports_total": len(ports),
            "summary": (
                f"{connected_n}/{len(ports)} Type-C cable(s)" if ports else "no Type-C ports"
            ),
        }

    type_a = usb_type_a_snapshot()
    return {
        **typec,
        "type_c": typec,
        "type_a": type_a,
    }


def device_snapshot(path: Path = DEVICE_STATE) -> dict[str, object]:
    """Compose chassis command-center state with live Type-C ports.

    Missing command-center.json is common on hosts without the overlay publisher;
    still surface I/O so the Device card is not a dead-end error string.
    """
    io = io_snapshot()
    ports = io.get("ports") if isinstance(io.get("ports"), list) else []
    connected = sum(1 for p in ports if isinstance(p, dict) and p.get("state") == "connected")
    total = len(ports)
    type_a = io.get("type_a") if isinstance(io.get("type_a"), dict) else {}
    type_a_ports = type_a.get("ports") if isinstance(type_a.get("ports"), list) else []
    type_a_connected = int(type_a.get("ports_connected") or 0)
    type_a_total = int(type_a.get("ports_total") or len(type_a_ports))

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        source = "command-center"
    except FileNotFoundError:
        value = {
            "availability": "partial" if total else "unavailable",
            "detail": "command button state offline",
        }
        source = "io-only"
    except (OSError, ValueError):
        value = {
            "availability": "partial" if total else "unavailable",
            "detail": "command button state unreadable",
        }
        source = "io-only"
    if not isinstance(value, dict):
        value = {"availability": "unavailable", "detail": "device state invalid"}
        source = "invalid"

    button = value.get("button") if isinstance(value.get("button"), dict) else {}
    button_state = str(button.get("state") or "") if button else ""

    # One short summary — Type-C + Type-A + chassis button; details in metrics.
    if total:
        c_bit = (
            f"{connected}/{total} Type-C linked"
            if connected
            else f"0/{total} Type-C (no cable)"
        )
    else:
        c_bit = "no Type-C"
    if type_a_total:
        a_bit = (
            f"{type_a_connected}/{type_a_total} Type-A linked"
            if type_a_connected
            else f"0/{type_a_total} Type-A idle"
        )
    else:
        a_bit = "no Type-A"
    cable = f"{c_bit} · {a_bit}"

    if source == "io-only":
        summary = f"Z13 chassis · {cable} · command button offline"
        availability = "partial" if (total or type_a_total) else "unavailable"
    else:
        availability = str(value.get("availability") or "available")
        base = str(value.get("summary") or "chassis online")
        if "type-c" in base.lower() or "type-a" in base.lower() or "cable" in base.lower():
            summary = base
        else:
            summary = f"{base} · {cable}"

    out = dict(value)
    out.update(
        {
            "availability": availability,
            "summary": summary,
            "detail": value.get("detail"),
            "source": source,
            "button_state": button_state or None,
            "chassis": "ROG Flow Z13",
            "io": io,
            "ports_connected": connected,
            "ports_total": total,
            "type_a_connected": type_a_connected,
            "type_a_total": type_a_total,
        }
    )
    return out


def _http_json(url: str, timeout: float = PROBE_TIMEOUT_S) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = json.load(response)
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_models_last_good: list[dict[str, object]] = []
_models_last_good_at = 0.0
_MODELS_STALE_S = 90.0


def loaded_models(*, timeout: float = PROBE_TIMEOUT_S) -> list[dict[str, object]]:
    """Best-effort loaded-model list. Must never block the portal refresh path.

    On lemonade probe miss, reuse last-good list briefly so the UI does not
    flash empty every few seconds under load.
    """
    global _models_last_good, _models_last_good_at
    models: list[dict[str, object]] = []
    data = _http_json(OLLAMA_MODELS, timeout=timeout)
    rows = data.get("models", []) if isinstance(data, dict) else []
    models.extend(row | {"backend": "ollama"} for row in rows if isinstance(row, dict))
    data = _http_json(LEMONADE_HEALTH, timeout=timeout)
    got_lemonade = bool(data)
    rows = data.get("all_models_loaded", []) if isinstance(data, dict) else []
    models.extend(
        row | {"backend": "lemonade"}
        for row in rows
        if isinstance(row, dict) and row.get("loaded")
    )
    if models:
        _models_last_good = models
        _models_last_good_at = time.monotonic()
        return models
    if (
        not got_lemonade
        and _models_last_good
        and (time.monotonic() - _models_last_good_at) < _MODELS_STALE_S
    ):
        return list(_models_last_good)
    return models


def _model_name(row: dict[str, object]) -> str:
    return str(row.get("model_name") or row.get("name") or row.get("checkpoint") or "unknown")


def _is_npu_model(row: dict[str, object]) -> bool:
    name = _model_name(row).lower()
    device = str(row.get("device") or "").lower()
    recipe = str(row.get("recipe") or "").lower()
    backend = str(row.get("backend") or "").lower()
    blob = f"{name} {device} {recipe} {backend}"
    return any(tok in blob for tok in ("flm", "npu", "xdna"))


def npu_snapshot(models: list[dict[str, object]], device: Path = NPU_DEVICE) -> dict[str, object]:
    try:
        service = subprocess.run(
            ["systemctl", "is-active", "lemonade.service"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1.0,
        ).stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        service = "unknown"
    if not device.exists():
        return {
            "availability": "unavailable",
            "summary": "XDNA NPU device not found",
            "service": service,
            "activity": "no device",
            "models": [],
            "entries": [],
        }
    npu_rows = [row for row in models if _is_npu_model(row)]
    entries: list[dict[str, object]] = []
    for row in npu_rows:
        ctx = None
        opts = row.get("recipe_options")
        if isinstance(opts, dict) and opts.get("ctx_size") is not None:
            ctx = opts.get("ctx_size")
        elif row.get("max_context_window") is not None:
            ctx = row.get("max_context_window")
        entries.append(
            {
                "name": _model_name(row),
                "device": row.get("device") or "npu",
                "recipe": row.get("recipe"),
                "pinned": bool(row.get("pinned")),
                "status": row.get("status") or row.get("backend_health"),
                "ctx": ctx,
            }
        )
    names = [str(e["name"]) for e in entries]
    if names:
        activity = f"{len(names)} NPU model(s) loaded"
        # Keep status line short — full names live in entries/metrics.
        summary = f"NPU · {len(names)} model(s) loaded"
    else:
        activity = (
            "idle — no FLM/NPU model in loaded list"
            if service == "active"
            else f"Lemonade {service}"
        )
        summary = "NPU ready · idle"
    return {
        "availability": "available",
        "summary": summary,
        "service": service,
        "activity": activity,
        "models": names,
        "entries": entries,
    }


def runtime_snapshot(
    models: list[dict[str, object]],
    services: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for row in models:
        entries.append(
            {
                "name": _model_name(row),
                "backend": row.get("backend") or "unknown",
                "device": row.get("device") or ("npu" if _is_npu_model(row) else "gpu"),
                "pinned": bool(row.get("pinned")),
                "status": row.get("status") or row.get("backend_health") or "loaded",
                "recipe": row.get("recipe"),
            }
        )
    services = services or []
    voice_ids = {"sensevoice", "kokoro", "pipecat", "mem0"}
    voice_up = sum(
        1
        for s in services
        if s.get("id") in voice_ids
        and (
            s.get("state") == "active"
            or (s.get("state") == "n/a" and s.get("health") is True)
        )
    )
    # Short stable status — long HuggingFace-style names go only in metrics rows.
    if entries:
        npu_n = sum(1 for e in entries if str(e.get("device") or "").lower() == "npu")
        gpu_n = len(entries) - npu_n
        bits = [f"{len(entries)} model(s)"]
        if npu_n:
            bits.append(f"{npu_n} npu")
        if gpu_n:
            bits.append(f"{gpu_n} gpu")
        summary = " · ".join(bits)
    else:
        summary = "No local models reported"
    return {
        "summary": summary,
        "model_count": len(entries),
        "models": entries,
        "voice_services_up": voice_up,
        "voice_services_total": len(voice_ids),
    }


def _build_snapshot(
    statuses: list[ServiceStatus] | None = None,
    *,
    models: list[dict[str, object]] | None = None,
    automation: list[dict[str, object]] | None = None,
    device_path: Path = DEVICE_STATE,
    npu_device: Path = NPU_DEVICE,
) -> dict[str, object]:
    statuses = probe_all(load_services()) if statuses is None else statuses
    models = loaded_models() if models is None else models
    automation = load_automation() if automation is None else automation
    services = [
        {
            "id": item.meta.id,
            "title": item.meta.title,
            "state": item.unit_state,
            "ui": item.meta.ui,
            "health": item.health_ok,
            "display_state": service_display_state(item.unit_state, item.health_ok),
            "can_start": service_can_start(item.unit_state, item.health_ok),
            "group": service_group(item.meta.id),
        }
        for item in statuses
    ]
    healthy = sum(
        item.health_ok is not False and item.unit_state in ("active", "n/a") for item in statuses
    )
    runtime = runtime_snapshot(models, services)
    device = device_snapshot(device_path)
    npu = npu_snapshot(models, npu_device)
    platform = platform_snapshot()
    return {
        "summary": f"{healthy}/{len(statuses)} services ready · {runtime['model_count']} model(s) · {platform['summary']}",
        "services": services,
        "automation": [
            {key: row.get(key) for key in ("task_id", "provider", "state", "branch")}
            for row in automation
            if row.get("task_id")
        ],
        "models": models,
        "platform": platform,
        "runtime": runtime,
        "device": device,
        "npu": npu,
    }


def snapshot(
    statuses: list[ServiceStatus] | None = None,
    *,
    models: list[dict[str, object]] | None = None,
    automation: list[dict[str, object]] | None = None,
    device_path: Path = DEVICE_STATE,
    npu_device: Path = NPU_DEVICE,
    use_cache: bool = True,
) -> dict[str, object]:
    """Dashboard snapshot. Caches live probes briefly so SPA 5s refresh cannot
    stampede Lemonade/LiteLLM while a previous probe is still draining."""
    if statuses is not None or models is not None or automation is not None or not use_cache:
        return _build_snapshot(
            statuses,
            models=models,
            automation=automation,
            device_path=device_path,
            npu_device=npu_device,
        )

    global _snapshot_cache, _snapshot_cache_at
    now = time.monotonic()
    with _snapshot_lock:
        if (
            _snapshot_cache is not None
            and (now - _snapshot_cache_at) < SNAPSHOT_CACHE_S
        ):
            return _snapshot_cache

    built = _build_snapshot(
        None,
        models=None,
        automation=None,
        device_path=device_path,
        npu_device=npu_device,
    )
    with _snapshot_lock:
        _snapshot_cache = built
        _snapshot_cache_at = time.monotonic()
    return built
