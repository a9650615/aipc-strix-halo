"""AIPC entry portal CLI helpers and live-host serve fallback.

The installed systemd unit runs the stdlib package under
modules/system-aipc-portal/files/usr/lib/aipc-portal/. This module mirrors
the metadata contract for tests/CLI and can serve from the repo before
bootc switch.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PKG = (
    REPO_ROOT
    / "modules"
    / "system-aipc-portal"
    / "files"
    / "usr"
    / "lib"
    / "aipc-portal"
)
INSTALLED_PKG = Path("/usr/lib/aipc-portal")
INSTALLED_SERVICES = Path("/etc/aipc/portal/services")
DEFAULT_ENDPOINT_FILE = REPO_ROOT / "modules" / "system-aipc-portal" / "env" / "endpoint"
INSTALLED_ENDPOINT_FILE = Path("/etc/aipc/env.d/system-aipc-portal/endpoint")
DEFAULT_URL = "http://127.0.0.1:7080"
PORTAL_UNIT = "aipc-portal.service"


@dataclass(frozen=True)
class ServiceMetadata:
    id: str
    title: str
    module: str
    kind: str
    systemd: str | None = None
    health: str | None = None
    endpoint: str | None = None
    ui: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    notes: str | None = None


def _parse_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_metadata(text: str) -> dict[str, object]:
    data: dict[str, object] = {}
    current_list: str | None = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_list and stripped.startswith("- "):
            items = data.setdefault(current_list, [])
            if isinstance(items, list):
                items.append(_parse_scalar(stripped[2:]))
            continue
        current_list = None
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "" or value in ("[]", "~", "null", "Null", "NULL"):
            if value in ("~", "null", "Null", "NULL"):
                data[key] = None
            else:
                data[key] = []
                current_list = key
        else:
            data[key] = _parse_scalar(value)
    return data


def _to_meta(data: dict[str, object]) -> ServiceMetadata | None:
    try:
        tags = data.get("tags", [])
        ui_raw = data.get("ui")
        ui = None if ui_raw in (None, "", "null") else str(ui_raw)
        return ServiceMetadata(
            id=str(data["id"]),
            title=str(data["title"]),
            module=str(data["module"]),
            kind=str(data["kind"]),
            systemd=str(data["systemd"]) if data.get("systemd") else None,
            health=str(data["health"]) if data.get("health") else None,
            endpoint=str(data["endpoint"]) if data.get("endpoint") else None,
            ui=ui,
            tags=tuple(str(t) for t in tags) if isinstance(tags, list) else (),
            notes=str(data["notes"]) if data.get("notes") else None,
        )
    except KeyError:
        return None


def load_service_metadata(
    root: Path = INSTALLED_SERVICES,
    *,
    roots: list[Path] | None = None,
) -> list[ServiceMetadata]:
    paths: list[Path] = []
    if roots is not None:
        for r in roots:
            if r.is_dir():
                paths.extend(sorted(r.glob("*.yaml")))
    elif root.exists():
        paths = sorted(root.glob("*.yaml"))
    services: list[ServiceMetadata] = []
    seen: set[str] = set()
    for path in paths:
        data = _parse_metadata(path.read_text(encoding="utf-8"))
        meta = _to_meta(data)
        if meta is None or meta.id in seen:
            continue
        seen.add(meta.id)
        services.append(meta)
    return services


def repo_services_dirs(repo_root: Path = REPO_ROOT) -> list[Path]:
    base = repo_root / "modules"
    if not base.is_dir():
        return []
    return sorted(
        p
        for p in base.glob("*/files/etc/aipc/portal/services")
        if p.is_dir()
    )


def resolve_services_roots(
    *,
    prefer_installed: bool = True,
    repo_root: Path = REPO_ROOT,
) -> list[Path]:
    roots: list[Path] = []
    if prefer_installed and INSTALLED_SERVICES.is_dir() and any(INSTALLED_SERVICES.glob("*.yaml")):
        roots.append(INSTALLED_SERVICES)
    for d in repo_services_dirs(repo_root):
        if d not in roots:
            roots.append(d)
    return roots


def unit_is_active(name: str, runner=subprocess.run) -> str:
    proc = runner(
        ["systemctl", "is-active", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or "").strip() or "inactive"


def http_probe(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")[:80].replace("\n", " ")
            return True, f"{resp.status} {body}".strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


@dataclass(frozen=True)
class CardProbe:
    meta: ServiceMetadata
    unit_state: str
    health_ok: bool | None
    health_detail: str

    @property
    def ok(self) -> bool:
        if self.meta.health is not None and self.health_ok is False:
            return False
        if self.meta.systemd and self.unit_state not in ("active", "n/a", "not probed"):
            if self.health_ok is not True:
                return False
        if self.meta.health is not None:
            return bool(self.health_ok)
        if self.meta.systemd:
            return self.unit_state == "active"
        return True


def probe_cards(
    services: list[ServiceMetadata],
    *,
    unit_active=unit_is_active,
    probe_http=http_probe,
) -> list[CardProbe]:
    out: list[CardProbe] = []
    for meta in services:
        unit_state = "n/a"
        if meta.systemd:
            unit_state = unit_active(meta.systemd)
        health_ok: bool | None = None
        health_detail = "not declared"
        if meta.health:
            health_ok, health_detail = probe_http(meta.health)
        out.append(CardProbe(meta, unit_state, health_ok, health_detail))
    return out


def render_portal_html(
    services: list[ServiceMetadata] | list[CardProbe],
    *,
    refresh_seconds: int = 5,
) -> str:
    """HTML cards; delegates to module package renderer when importable."""
    reg = _try_import_registry()
    if reg is not None and services:
        if isinstance(services[0], CardProbe):
            statuses = []
            for c in services:
                assert isinstance(c, CardProbe)
                meta = reg.ServiceMetadata(
                    id=c.meta.id,
                    title=c.meta.title,
                    module=c.meta.module,
                    kind=c.meta.kind,
                    systemd=c.meta.systemd,
                    health=c.meta.health,
                    endpoint=c.meta.endpoint,
                    ui=c.meta.ui,
                    tags=c.meta.tags,
                    notes=c.meta.notes,
                )
                statuses.append(
                    reg.ServiceStatus(meta, c.unit_state, c.health_ok, c.health_detail)
                )
            return reg.render_portal_html(statuses, refresh_seconds=refresh_seconds)
        converted = [
            reg.ServiceMetadata(
                id=s.id,
                title=s.title,
                module=s.module,
                kind=s.kind,
                systemd=s.systemd,
                health=s.health,
                endpoint=s.endpoint,
                ui=s.ui,
                tags=s.tags,
                notes=s.notes,
            )
            for s in services
            if isinstance(s, ServiceMetadata)
        ]
        return reg.render_portal_html(converted, refresh_seconds=refresh_seconds)
    if reg is not None and not services:
        return reg.render_portal_html([], refresh_seconds=refresh_seconds)
    return _render_html_fallback(services, refresh_seconds=refresh_seconds)


def _render_html_fallback(
    services: list[ServiceMetadata] | list[CardProbe],
    *,
    refresh_seconds: int = 5,
) -> str:
    import html as html_mod

    cards: list[str] = []
    for item in services:
        if isinstance(item, CardProbe):
            meta = item.meta
            unit_state = item.unit_state
            health_label = item.health_detail
        else:
            meta = item
            unit_state = "not probed"
            health_label = meta.health or "not declared"
        title = html_mod.escape(meta.title)
        module = html_mod.escape(meta.module)
        kind = html_mod.escape(meta.kind)
        endpoint = html_mod.escape(meta.endpoint or "not declared")
        link = ""
        if meta.ui:
            href = html_mod.escape(meta.ui, quote=True)
            link = f'<a class="button" href="{href}">Open</a>'
        cards.append(
            f'<article class="card"><h2>{title}</h2>'
            f'<p class="meta">{module} · {kind}</p>'
            f"<p>Unit: <code>{html_mod.escape(unit_state)}</code></p>"
            f"<p>Health: <code>{html_mod.escape(health_label)}</code></p>"
            f"<p>Endpoint: <code>{endpoint}</code></p>{link}</article>"
        )
    body = "\n".join(cards) or '<p class="empty">No AIPC services declared yet.</p>'
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f'<meta http-equiv="refresh" content="{int(refresh_seconds)}">'
        "<title>AIPC Portal</title></head><body><main><h1>AIPC Portal</h1>"
        f'<section class="grid">{body}</section></main></body></html>'
    )


def portal_url(
    endpoint_file: Path | None = None,
) -> str:
    candidates = []
    if endpoint_file is not None:
        candidates.append(endpoint_file)
    else:
        candidates.extend([INSTALLED_ENDPOINT_FILE, DEFAULT_ENDPOINT_FILE])
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8").strip().rstrip("/")
    return DEFAULT_URL


def portal_status(url: str) -> str:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/healthz", timeout=2) as response:
            return "running" if 200 <= response.status < 300 else "unhealthy"
    except Exception:
        return "unreachable"


def open_portal(
    url: str,
    runner: Callable[..., object] | None = None,
) -> None:
    argv = ["xdg-open", url]
    if runner is None:
        try:
            subprocess.check_call(argv)
            return
        except Exception:
            webbrowser.open(url)
            return
    try:
        runner(argv, True)  # type: ignore[misc]
    except TypeError:
        runner(argv)  # type: ignore[misc]


def format_status_lines(
    probes: list[CardProbe],
    *,
    url: str,
    server_state: str,
) -> str:
    lines = [f"portal: {url}  ({server_state})"]
    if not probes:
        lines.append("(no service cards declared)")
        return "\n".join(lines)
    width = max(len(p.meta.id) for p in probes)
    for p in probes:
        mark = "ok" if p.ok else "!!"
        unit = p.unit_state
        health = p.health_detail if p.meta.health else "n/a"
        lines.append(f"{mark}  {p.meta.id:<{width}}  unit={unit}  health={health}")
    return "\n".join(lines)


def collect_status(
    *,
    roots: list[Path] | None = None,
    unit_active=unit_is_active,
    probe_http=http_probe,
) -> list[CardProbe]:
    if roots is None:
        roots = resolve_services_roots()
    services = load_service_metadata(roots=roots)
    return probe_cards(services, unit_active=unit_active, probe_http=probe_http)


def unit_active_bool(name: str = PORTAL_UNIT, runner=subprocess.run) -> bool:
    return unit_is_active(name, runner=runner) == "active"


def package_root() -> Path | None:
    if (INSTALLED_PKG / "aipc_portal" / "server.py").is_file():
        return INSTALLED_PKG
    if (MODULE_PKG / "aipc_portal" / "server.py").is_file():
        return MODULE_PKG
    return None


def _try_import_registry():
    root = package_root()
    if root is None:
        return None
    reg_path = root / "aipc_portal" / "registry.py"
    if not reg_path.is_file():
        return None
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        import aipc_portal.registry as reg  # type: ignore

        return reg
    except Exception:
        spec = importlib.util.spec_from_file_location("aipc_portal_registry", reg_path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 7080,
    roots: list[Path] | None = None,
) -> None:
    """Run portal HTTP server in the foreground (dev / live-host)."""
    if roots is None:
        roots = resolve_services_roots()
    root = package_root()
    if root is None:
        raise RuntimeError(
            "portal package not found under /usr/lib/aipc-portal or "
            "modules/system-aipc-portal/files/usr/lib/aipc-portal"
        )
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import os

    if roots:
        os.environ["AIPC_PORTAL_SERVICES"] = ":".join(str(p) for p in roots)
    from aipc_portal.server import main as server_main  # type: ignore

    server_main(host=host, port=port)
