from __future__ import annotations

import html
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SERVICES_DIR = Path("/etc/aipc/portal/services")


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


@dataclass(frozen=True)
class ServiceStatus:
    meta: ServiceMetadata
    unit_state: str
    health_ok: bool | None
    health_detail: str


def _parse_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_metadata(text: str) -> dict[str, object]:
    """Minimal YAML subset: top-level scalars + one-level lists of scalars."""
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
    root: Path = SERVICES_DIR,
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


def probe_service(
    meta: ServiceMetadata,
    *,
    unit_active=unit_is_active,
    probe_http=http_probe,
) -> ServiceStatus:
    unit_state = "n/a"
    if meta.systemd:
        unit_state = unit_active(meta.systemd)
    health_ok: bool | None = None
    health_detail = "not declared"
    if meta.health:
        health_ok, health_detail = probe_http(meta.health)
    return ServiceStatus(meta, unit_state, health_ok, health_detail)


def probe_all(
    services: list[ServiceMetadata],
    *,
    unit_active=unit_is_active,
    probe_http=http_probe,
) -> list[ServiceStatus]:
    return [
        probe_service(s, unit_active=unit_active, probe_http=probe_http) for s in services
    ]


def render_portal_html(
    services: list[ServiceMetadata] | list[ServiceStatus],
    *,
    refresh_seconds: int = 5,
) -> str:
    cards: list[str] = []
    for item in services:
        if isinstance(item, ServiceStatus):
            meta = item.meta
            unit_state = item.unit_state
            if item.health_ok is True:
                health_label = f"ok — {item.health_detail}"
                badge = "ok"
            elif item.health_ok is False:
                health_label = f"fail — {item.health_detail}"
                badge = "bad"
            else:
                health_label = item.health_detail
                badge = "na"
            if meta.systemd and unit_state == "active" and item.health_ok is not False:
                badge = "ok" if item.health_ok is not False else badge
            if meta.systemd and unit_state not in ("active", "n/a") and item.health_ok is not True:
                badge = "bad"
        else:
            meta = item
            unit_state = "not probed"
            health_label = meta.health or "not declared"
            badge = "na"

        title = html.escape(meta.title)
        module = html.escape(meta.module)
        kind = html.escape(meta.kind)
        endpoint = html.escape(meta.endpoint or "not declared")
        unit_disp = html.escape(unit_state)
        health_disp = html.escape(health_label)
        notes = html.escape(meta.notes) if meta.notes else ""
        link = ""
        if meta.ui:
            href = html.escape(meta.ui, quote=True)
            link = f'<a class="button" href="{href}">Open</a>'
        notes_html = f'<p class="notes">{notes}</p>' if notes else ""
        cards.append(
            f"""
            <article class="card badge-{badge}">
              <h2>{title}</h2>
              <p class="meta">{module} · {kind}</p>
              <p>Unit: <code>{unit_disp}</code></p>
              <p>Health: <code>{health_disp}</code></p>
              <p>Endpoint: <code>{endpoint}</code></p>
              {notes_html}
              {link}
            </article>
            """
        )
    body = "\n".join(cards) or '<p class="empty">No AIPC services declared yet.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{int(refresh_seconds)}">
<title>AIPC Portal</title>
<style>
body {{ margin: 0; font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 32px; }}
h1 {{ margin-top: 0; }}
.sub {{ color: #94a3b8; margin-bottom: 24px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
.card {{ background: #111827; border: 1px solid #334155; border-radius: 14px; padding: 18px; }}
.card.badge-ok {{ border-color: #166534; }}
.card.badge-bad {{ border-color: #991b1b; }}
.meta {{ color: #94a3b8; }}
.notes {{ color: #cbd5e1; font-size: 0.9rem; }}
code {{ color: #bae6fd; overflow-wrap: anywhere; }}
.button {{ display: inline-block; margin-top: 8px; padding: 8px 12px; border-radius: 10px;
  background: #38bdf8; color: #082f49; text-decoration: none; font-weight: 700; }}
.empty {{ color: #94a3b8; }}
</style>
</head>
<body>
<main>
  <h1>AIPC Portal</h1>
  <p class="sub">localhost only · auto-refresh {int(refresh_seconds)}s · metadata from /etc/aipc/portal/services</p>
  <section class="grid">{body}</section>
</main>
</body>
</html>
"""


def load_services(
    roots: list[Path] | None = None,
) -> list[ServiceMetadata]:
    if roots is not None:
        return load_service_metadata(roots=roots)
    return load_service_metadata(SERVICES_DIR)


def render(roots: list[Path] | None = None) -> str:
    services = load_services(roots=roots)
    statuses = probe_all(services)
    return render_portal_html(statuses)
