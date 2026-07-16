from __future__ import annotations

import html
import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SERVICES_DIR = Path("/etc/aipc/portal/services")
AUTOMATION_URL = "http://127.0.0.1:4100/automation"


@dataclass(frozen=True)
class ServiceMetadata:
    id: str
    title: str
    module: str
    kind: str
    systemd: str | None = None
    # system (default) | user — user units need --user -M <primary>@
    systemd_scope: str = "system"
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
        health_raw = data.get("health")
        health = (
            None
            if health_raw in (None, "", "null", "Null", "NULL", "~")
            else str(health_raw)
        )
        scope_raw = str(data.get("systemd_scope") or "system").strip().lower()
        scope = "user" if scope_raw in ("user", "usr") else "system"
        return ServiceMetadata(
            id=str(data["id"]),
            title=str(data["title"]),
            module=str(data["module"]),
            kind=str(data["kind"]),
            systemd=str(data["systemd"]) if data.get("systemd") else None,
            systemd_scope=scope,
            health=health,
            endpoint=str(data["endpoint"]) if data.get("endpoint") else None,
            ui=ui,
            tags=tuple(str(t) for t in tags) if isinstance(tags, list) else (),
            notes=str(data["notes"]) if data.get("notes") else None,
        )
    except KeyError:
        return None


def primary_user(env: dict[str, str] | None = None) -> str:
    """Desktop user whose --user bus owns OAuth-backed units (CLIProxy, usage)."""
    e = env if env is not None else os.environ
    return (e.get("AIPC_PRIMARY_USER") or e.get("AIPC_HERMES_USER") or "").strip()


def _user_runtime_dir(username: str) -> str:
    """XDG_RUNTIME_DIR for a login user (needed by systemctl --user)."""
    try:
        import pwd

        uid = pwd.getpwnam(username).pw_uid
    except Exception:
        return ""
    return f"/run/user/{uid}"


def unit_command(
    action: str,
    name: str,
    *,
    scope: str = "system",
    user: str | None = None,
) -> list[str]:
    """Build systemctl argv for system or user scope.

    User units are owned by the desktop session. Calling
    ``systemctl --user -M user@`` from a long-running *system* service
    (aipc-portal) fails on this host with ``Connection reset by peer`` /
    disconnected bus. ``runuser`` + ``XDG_RUNTIME_DIR`` talks to the user
    manager the same way an interactive shell would, and is hardware-proven
    from the portal cgroup.
    """
    if scope == "user":
        u = (user or primary_user()).strip() or "unknown"
        runtime = _user_runtime_dir(u)
        env_runtime = f"XDG_RUNTIME_DIR={runtime}" if runtime else "XDG_RUNTIME_DIR="
        return [
            "runuser",
            "-u",
            u,
            "--",
            "env",
            env_runtime,
            "systemctl",
            "--user",
            action,
            name,
        ]
    return ["systemctl", action, name]


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


def unit_is_active(
    name: str,
    runner=subprocess.run,
    *,
    scope: str = "system",
    user: str | None = None,
) -> str:
    proc = runner(
        unit_command("is-active", name, scope=scope, user=user),
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or "").strip() or "inactive"


def http_probe(url: str, timeout: float = 0.5) -> tuple[bool, str]:
    """Cheap liveness probe. Keep timeout short so a thrashing backend cannot
    pin portal request threads (and pile ESTAB connections) for seconds."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")[:80].replace("\n", " ")
            return True, f"{resp.status} {body}".strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def load_automation(url: str = AUTOMATION_URL, timeout: float = 0.5) -> list[dict[str, object]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rows = data.get("automation", []) if isinstance(data, dict) else []
        return [row for row in rows if isinstance(row, dict)]
    except (OSError, ValueError, urllib.error.URLError):
        return []


def probe_service(
    meta: ServiceMetadata,
    *,
    unit_active=unit_is_active,
    probe_http=http_probe,
) -> ServiceStatus:
    unit_state = "n/a"
    if meta.systemd:
        scope = getattr(meta, "systemd_scope", "system") or "system"
        try:
            unit_state = unit_active(meta.systemd, scope=scope)
        except TypeError:
            # Older test doubles only accept the unit name.
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


def start_unit(
    name: str,
    runner=subprocess.run,
    *,
    scope: str = "system",
    user: str | None = None,
) -> tuple[bool, str]:
    """Start a declared systemd unit (localhost manage action)."""
    if not name or not all(c.isalnum() or c in ".-_@" for c in name):
        return False, "invalid unit name"
    if scope == "user" and not (user or primary_user()).strip():
        return False, "AIPC_PRIMARY_USER unset (cannot start user unit)"
    primary = unit_command("start", name, scope=scope, user=user)
    candidates = [primary]
    # System units may need passwordless sudo when portal is unprivileged.
    if scope != "user":
        candidates.append(["sudo", "-n", *primary])
    last_detail = "start failed"
    for argv in candidates:
        proc = runner(argv, capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            return True, "started"
        last_detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        # try next candidate
    return False, last_detail


def find_service(
    service_id: str,
    roots: list[Path] | None = None,
) -> ServiceMetadata | None:
    for meta in load_services(roots=roots):
        if meta.id == service_id:
            return meta
    return None


def start_service(
    service_id: str,
    *,
    roots: list[Path] | None = None,
    runner=subprocess.run,
) -> tuple[bool, str]:
    meta = find_service(service_id, roots=roots)
    if meta is None:
        return False, "unknown service"
    if not meta.systemd:
        return False, "no systemd unit declared"
    return start_unit(
        meta.systemd,
        runner=runner,
        scope=getattr(meta, "systemd_scope", "system") or "system",
    )


def start_baseline_services(
    *,
    roots: list[Path] | None = None,
    runner=subprocess.run,
) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    for meta in load_services(roots=roots):
        if "baseline" not in meta.tags or not meta.systemd:
            continue
        ok, detail = start_unit(
            meta.systemd,
            runner=runner,
            scope=getattr(meta, "systemd_scope", "system") or "system",
        )
        results.append((meta.id, ok, detail))
    return results


def _normalize_status(
    item: ServiceMetadata | ServiceStatus,
) -> tuple[ServiceMetadata, str, str, str, bool | None]:
    """Return meta, unit_state, health_label, badge, health_ok."""
    if isinstance(item, ServiceStatus):
        meta = item.meta
        unit_state = item.unit_state
        health_ok = item.health_ok
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
            badge = "ok"
        if meta.systemd and unit_state not in ("active", "n/a") and item.health_ok is not True:
            badge = "bad"
        return meta, unit_state, health_label, badge, health_ok

    meta = item
    return meta, "not probed", meta.health or "not declared", "na", None


def _status_phrase(badge: str, unit_state: str, health_ok: bool | None) -> str:
    if badge == "ok":
        return "Healthy"
    if badge == "bad":
        if unit_state not in ("active", "n/a", "not probed") and health_ok is not True:
            return "Down"
        if health_ok is False:
            return "Unhealthy"
        return "Degraded"
    if unit_state == "n/a" and health_ok is None:
        return "Helpers only"
    return "Unknown"


def _card_role(meta: ServiceMetadata) -> str:
    tags = set(meta.tags)
    if "stt" in tags:
        return "Speech-to-text"
    if "tts" in tags:
        return "Text-to-speech"
    if "gateway" in tags:
        return "LLM gateway"
    if "npu" in tags or (meta.kind == "llm" and "baseline" in tags):
        return "Local LLM"
    if meta.kind == "memory":
        return "Long-term memory"
    if meta.kind == "agent" or "session" in tags:
        return "Agent sessions"
    if "helpers" in tags:
        return "Voice helpers"
    if "dashboard" in tags:
        return "This portal"
    return meta.kind.replace("-", " ").title() or "Service"


KIND_ORDER = ("voice", "llm", "memory", "agent", "system")
KIND_LABELS = {
    "voice": "Voice",
    "llm": "Models & gateway",
    "memory": "Memory",
    "agent": "Agent work",
    "system": "System",
}

# Closed loop stages — matched via tags/kind only (no service-specific UI logic).
LOOP_STAGES: tuple[tuple[str, str, str], ...] = (
    ("hear", "Hear", "stt"),
    ("think", "Think", "llm"),
    ("speak", "Speak", "tts"),
    ("remember", "Remember", "memory"),
    ("manage", "Manage", "dashboard"),
)


def _stage_match(meta: ServiceMetadata, stage_key: str, tag: str) -> int:
    """Higher score = better representative for the closed-loop stage."""
    tags = set(meta.tags)
    score = 0
    if stage_key == "hear" and ("stt" in tags or tag in tags):
        score = 10 + (2 if "baseline" in tags else 0)
    elif stage_key == "think" and meta.kind == "llm":
        score = 8 + (3 if "baseline" in tags else 0) + (1 if "gateway" not in tags else 0)
    elif stage_key == "speak" and ("tts" in tags or tag in tags):
        score = 10 + (2 if "baseline" in tags else 0)
    elif stage_key == "remember" and (meta.kind == "memory" or "memory" in tags):
        score = 10 + (2 if "baseline" in tags else 0)
    elif stage_key == "manage" and ("dashboard" in tags or meta.id == "aipc-portal"):
        score = 10
    return score


def _loop_stages(
    statuses: list[tuple[ServiceMetadata, str, str, str, bool | None]],
) -> list[dict[str, str]]:
    stages: list[dict[str, str]] = []
    for key, label, tag in LOOP_STAGES:
        best: tuple[int, ServiceMetadata, str, str] | None = None
        for meta, unit_state, _health_label, badge, _ok in statuses:
            score = _stage_match(meta, key, tag)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, meta, badge, unit_state)
        if best is None:
            stages.append(
                {
                    "key": key,
                    "label": label,
                    "badge": "na",
                    "title": "not declared",
                    "hint": "no metadata",
                }
            )
        else:
            _score, meta, badge, unit_state = best
            stages.append(
                {
                    "key": key,
                    "label": label,
                    "badge": badge,
                    "title": meta.title,
                    "hint": unit_state if meta.systemd else "ready",
                }
            )
    return stages


def _render_service_card(
    meta: ServiceMetadata,
    unit_state: str,
    health_label: str,
    badge: str,
    health_ok: bool | None,
) -> str:
    title = html.escape(meta.title)
    module = html.escape(meta.module)
    role = html.escape(_card_role(meta))
    status_txt = html.escape(_status_phrase(badge, unit_state, health_ok))
    unit_disp = html.escape(unit_state)
    health_disp = html.escape(health_label)
    notes = html.escape(meta.notes) if meta.notes else ""
    actions: list[str] = []
    if meta.ui:
        href = html.escape(meta.ui, quote=True)
        actions.append(f'<a class="button" href="{href}">Open UI</a>')
    if meta.systemd and unit_state not in ("active", "n/a", "not probed"):
        sid = html.escape(meta.id, quote=True)
        actions.append(
            f'<form class="inline" method="post" action="/services/{sid}/start">'
            f'<button class="button secondary" type="submit">Start unit</button></form>'
        )
    if meta.endpoint:
        ep = html.escape(meta.endpoint, quote=True)
        actions.append(
            f'<button type="button" class="button ghost copy-btn" data-copy="{ep}">'
            f"Copy endpoint</button>"
        )
    actions_html = f'<div class="actions">{"".join(actions)}</div>' if actions else ""
    notes_html = f'<p class="notes">{notes}</p>' if notes else ""
    endpoint_row = ""
    if meta.endpoint:
        endpoint_row = (
            f"<details><summary>Technical</summary>"
            f"<p>Module: <code>{module}</code></p>"
            f"<p>Unit: <code>{unit_disp}</code></p>"
            f"<p>Health: <code>{health_disp}</code></p>"
            f"<p>Endpoint: <code>{html.escape(meta.endpoint)}</code></p>"
            f"</details>"
        )
    else:
        endpoint_row = (
            f"<details><summary>Technical</summary>"
            f"<p>Module: <code>{module}</code></p>"
            f"<p>Unit: <code>{unit_disp}</code></p>"
            f"<p>Health: <code>{health_disp}</code></p>"
            f"<p>Endpoint: not declared</p></details>"
        )
    return f"""
    <article class="card badge-{badge}">
      <div class="card-top">
        <span class="pill pill-{badge}">{status_txt}</span>
        <span class="role">{role}</span>
      </div>
      <h3>{title}</h3>
      {notes_html}
      {actions_html}
      {endpoint_row}
    </article>
    """


def render_portal_html(
    services: list[ServiceMetadata] | list[ServiceStatus],
    *,
    refresh_seconds: int = 5,
    automation: list[dict[str, object]] | None = None,
) -> str:
    normalized = [_normalize_status(item) for item in services]
    ok_n = sum(1 for _m, _u, _h, b, _o in normalized if b == "ok")
    bad_n = sum(1 for _m, _u, _h, b, _o in normalized if b == "bad")
    total_n = len(normalized)
    stages = _loop_stages(normalized)
    loop_ok = sum(1 for s in stages if s["badge"] == "ok")
    loop_total = sum(1 for s in stages if s["badge"] != "na")

    stage_html_parts: list[str] = []
    for i, stage in enumerate(stages):
        if i:
            stage_html_parts.append('<span class="loop-arrow" aria-hidden="true">→</span>')
        stage_html_parts.append(
            f'<div class="loop-stage badge-{html.escape(stage["badge"])}">'
            f'<span class="loop-label">{html.escape(stage["label"])}</span>'
            f'<span class="loop-title">{html.escape(stage["title"])}</span>'
            f'<span class="loop-hint">{html.escape(stage["hint"])}</span>'
            f"</div>"
        )
    loop_html = "\n".join(stage_html_parts)

    if bad_n:
        summary = f"{ok_n}/{total_n} services healthy · {bad_n} need attention"
        summary_class = "summary bad"
    elif total_n and ok_n == total_n:
        summary = f"All {total_n} services healthy · closed loop {loop_ok}/{loop_total or 0}"
        summary_class = "summary ok"
    else:
        summary = f"{ok_n}/{total_n or 0} healthy · closed loop {loop_ok}/{loop_total or 0}"
        summary_class = "summary"

    by_kind: dict[str, list[str]] = {}
    for meta, unit_state, health_label, badge, health_ok in normalized:
        kind = meta.kind or "other"
        by_kind.setdefault(kind, []).append(
            _render_service_card(meta, unit_state, health_label, badge, health_ok)
        )

    group_sections: list[str] = []
    seen_kinds: set[str] = set()
    for kind in KIND_ORDER:
        cards = by_kind.get(kind)
        if not cards:
            continue
        seen_kinds.add(kind)
        label = KIND_LABELS.get(kind, kind.title())
        group_sections.append(
            f'<section class="group"><h2>{html.escape(label)}</h2>'
            f'<div class="grid">{"".join(cards)}</div></section>'
        )
    for kind in sorted(k for k in by_kind if k not in seen_kinds):
        cards = by_kind[kind]
        group_sections.append(
            f'<section class="group"><h2>{html.escape(kind.title())}</h2>'
            f'<div class="grid">{"".join(cards)}</div></section>'
        )
    groups_html = "\n".join(group_sections) or (
        '<p class="empty">No AIPC services declared yet.</p>'
    )

    control_cards: list[str] = []
    for row in automation or []:
        task_id = html.escape(str(row.get("task_id") or ""))
        provider = html.escape(str(row.get("provider") or "unknown"))
        repo = html.escape(str(row.get("repo") or "unknown"))
        branch = html.escape(str(row.get("branch") or "detached"))
        state = html.escape(str(row.get("state") or "unknown"))
        pid = html.escape(str(row.get("pid") or "-"))
        elapsed = html.escape(str(row.get("elapsed_s") or 0))
        activity = html.escape(str(row.get("last_activity") or ""))
        cancel = ""
        if state in ("running", "cancelling") and task_id:
            cancel = (
                f'<form method="post" action="/automation/{task_id}/cancel">'
                '<button class="danger" type="submit">Cancel</button></form>'
            )
        control_cards.append(
            f'<article class="card control"><h3>{provider}</h3>'
            f'<p class="meta">{state} · PID {pid} · {elapsed}s</p>'
            f'<p>Repo: <code>{repo}</code></p><p>Branch: <code>{branch}</code></p>'
            f'<p>{activity}</p>{cancel}</article>'
        )
    controls = "\n".join(control_cards) or (
        '<p class="empty">No assistant-controlled CLI tasks right now.</p>'
    )

    cmd_chips = [
        ("Voice status", "aipc voice status"),
        ("Start baseline", "aipc voice start"),
        ("Push-to-talk", "aipc-voice-once"),
        ("Open portal", "aipc portal open"),
    ]
    chips_html = "".join(
        f'<button type="button" class="chip copy-btn" data-copy="{html.escape(cmd, quote=True)}">'
        f"{html.escape(label)} <code>{html.escape(cmd)}</code></button>"
        for label, cmd in cmd_chips
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{int(refresh_seconds)}">
<title>AIPC Portal</title>
<style>
:root {{
  --bg: #0b1220;
  --panel: #111827;
  --border: #334155;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --ok: #16a34a;
  --bad: #dc2626;
  --warn: #ca8a04;
  --accent: #38bdf8;
  --accent-ink: #082f49;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: system-ui, -apple-system, sans-serif;
  background: radial-gradient(1200px 600px at 10% -10%, #1e293b 0%, var(--bg) 55%);
  color: var(--text); min-height: 100vh; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 28px 20px 48px; }}
header.hero {{ margin-bottom: 20px; }}
h1 {{ margin: 0 0 6px; font-size: 1.75rem; letter-spacing: -0.02em; }}
h2 {{ margin: 28px 0 12px; font-size: 1.05rem; color: #cbd5e1; font-weight: 650; }}
h3 {{ margin: 8px 0 6px; font-size: 1.05rem; }}
.sub {{ color: var(--muted); margin: 0 0 14px; font-size: 0.92rem; }}
.summary {{ display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px;
  border-radius: 999px; background: #1e293b; border: 1px solid var(--border);
  color: var(--muted); font-size: 0.9rem; margin-bottom: 16px; }}
.summary.ok {{ border-color: #166534; color: #86efac; }}
.summary.bad {{ border-color: #7f1d1d; color: #fca5a5; }}
.loop {{ display: flex; flex-wrap: wrap; align-items: stretch; gap: 8px;
  padding: 14px; border-radius: 16px; background: var(--panel);
  border: 1px solid var(--border); margin-bottom: 18px; }}
.loop-stage {{ flex: 1 1 110px; min-width: 100px; padding: 10px 12px;
  border-radius: 12px; background: #0f172a; border: 1px solid var(--border); }}
.loop-stage.badge-ok {{ border-color: #166534; box-shadow: inset 0 0 0 1px #14532d55; }}
.loop-stage.badge-bad {{ border-color: #991b1b; box-shadow: inset 0 0 0 1px #7f1d1d66; }}
.loop-stage.badge-na {{ opacity: 0.7; }}
.loop-label {{ display: block; font-size: 0.72rem; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); font-weight: 700; }}
.loop-title {{ display: block; margin-top: 4px; font-weight: 650; font-size: 0.92rem; }}
.loop-hint {{ display: block; margin-top: 2px; color: var(--muted); font-size: 0.78rem; }}
.loop-arrow {{ align-self: center; color: #475569; font-weight: 700; padding: 0 2px; }}
.ops {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }}
.chip, .button, .danger {{ font: inherit; cursor: pointer; border: 0; }}
.chip {{ display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px;
  border-radius: 12px; background: #1e293b; color: var(--text);
  border: 1px solid var(--border); text-align: left; }}
.chip code {{ color: var(--accent); font-size: 0.82rem; }}
.chip:hover, .button:hover {{ filter: brightness(1.08); }}
.ops-row {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
  margin: 10px 0 4px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; }}
.card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
  padding: 16px; display: flex; flex-direction: column; gap: 6px; }}
.card.badge-ok {{ border-color: #166534; }}
.card.badge-bad {{ border-color: #991b1b; }}
.card.control {{ border-color: #a16207; }}
.card-top {{ display: flex; justify-content: space-between; gap: 8px; align-items: center; }}
.pill {{ font-size: 0.72rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 999px; background: #1e293b; color: var(--muted); }}
.pill-ok {{ background: #14532d; color: #bbf7d0; }}
.pill-bad {{ background: #7f1d1d; color: #fecaca; }}
.pill-na {{ background: #1e293b; color: #94a3b8; }}
.role {{ color: var(--muted); font-size: 0.82rem; }}
.meta {{ color: var(--muted); }}
.notes {{ color: #cbd5e1; font-size: 0.9rem; margin: 0; }}
code {{ color: #bae6fd; overflow-wrap: anywhere; }}
.actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }}
.button {{ display: inline-block; padding: 8px 12px; border-radius: 10px;
  background: var(--accent); color: var(--accent-ink); text-decoration: none; font-weight: 700; }}
.button.secondary {{ background: #334155; color: #e2e8f0; }}
.button.ghost {{ background: transparent; color: var(--accent);
  border: 1px solid #0e7490; }}
.inline {{ display: inline; margin: 0; }}
details {{ margin-top: 6px; color: var(--muted); font-size: 0.85rem; }}
details summary {{ cursor: pointer; color: #64748b; }}
details p {{ margin: 6px 0 0; }}
.empty {{ color: var(--muted); }}
.danger {{ padding: 8px 12px; border-radius: 10px; background: #ef4444;
  color: white; font-weight: 700; }}
.toast {{ position: fixed; bottom: 18px; right: 18px; background: #0f172a;
  border: 1px solid var(--border); padding: 10px 14px; border-radius: 10px;
  color: var(--text); opacity: 0; pointer-events: none; transition: opacity .15s; z-index: 20; }}
.toast.show {{ opacity: 1; }}
@media (max-width: 640px) {{
  .loop-arrow {{ display: none; }}
  main {{ padding: 18px 14px 40px; }}
}}
</style>
</head>
<body>
<main>
  <header class="hero">
    <h1>AIPC Portal</h1>
    <p class="sub">Local manage surface · hear → think → speak → remember · auto-refresh {int(refresh_seconds)}s · 127.0.0.1 only</p>
    <div class="{summary_class}">{html.escape(summary)}</div>
  </header>

  <section class="loop" aria-label="Closed loop status">{loop_html}</section>

  <section>
    <h2>Quick commands</h2>
    <p class="sub">Click a chip to copy — run in a terminal. Baseline start also available as a local action.</p>
    <div class="ops">{chips_html}</div>
    <div class="ops-row">
      <form method="post" action="/ops/baseline/start">
        <button class="button secondary" type="submit">Start baseline units</button>
      </form>
    </div>
  </section>

  <section>
    <h2>Live work</h2>
    <div class="grid">{controls}</div>
  </section>

  {groups_html}

  <div id="toast" class="toast" role="status" aria-live="polite"></div>
</main>
<script>
(function () {{
  var toast = document.getElementById('toast');
  function show(msg) {{
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(function () {{ toast.classList.remove('show'); }}, 1400);
  }}
  document.querySelectorAll('.copy-btn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      var text = btn.getAttribute('data-copy') || '';
      if (!text) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(text).then(function () {{ show('Copied: ' + text); }})
          .catch(function () {{ show(text); }});
      }} else {{
        show(text);
      }}
    }});
  }});
}})();
</script>
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
    return render_portal_html(statuses, automation=load_automation())
