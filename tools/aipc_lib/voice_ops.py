"""Always-on voice + memory baseline management for the aipc CLI.

Standing decision (2026-07-10): resident-small + SenseVoice + Kokoro + mem0
stay up unless a better combo is hardware-proven. Role presets (agent/voice/free)
only move heavy LLMs — never these services.

Install path remains modules/ (bootc / ansible). This module is the runtime
control plane: status, start, stop, and thin wrappers for shipped helpers.
"""
from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# systemd units for the always-on closed loop (voice + memory + chat entry).
BASELINE_UNITS: tuple[str, ...] = (
    "aipc-voice-stt-sensevoice.service",
    "aipc-kokoro.service",
    "aipc-mem0.service",
    "aipc-agent-orchestrator.service",
    "lemonade.service",
    "litellm.service",
)

# When quadlet unit is missing on a live/hotfix host, manage by container name.
KOKORO_CONTAINER = "aipc-kokoro"

HELPERS: dict[str, str] = {
    "once": "aipc-voice-once",
    "say": "aipc-voice-say",
    "stream": "aipc-voice-stream",
    "bind-hotkey": "aipc-voice-bind-hotkey",
    "record-clone": "aipc-voice-record-clone",
    "status-script": "aipc-voice-status",
    "krunner-install": "aipc-krunner-install",
    "overlay": "aipc-voice-overlay",
    "template": "aipc-voice-template",
}


@dataclass(frozen=True)
class Probe:
    name: str
    detail: str
    ok: bool


def unit_is_active(name: str, runner=subprocess.run) -> str:
    proc = runner(
        ["systemctl", "is-active", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or "").strip() or "inactive"


def unit_exists(name: str, runner=subprocess.run) -> bool:
    proc = runner(
        ["systemctl", "cat", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def container_status(name: str, runner=subprocess.run) -> str:
    proc = runner(
        ["podman", "inspect", "-f", "{{.State.Status}}", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return "absent"
    return (proc.stdout or "").strip() or "unknown"


def http_probe(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")[:120].replace("\n", " ")
            return True, f"{resp.status} {body}"
    except Exception as exc:  # noqa: BLE001 — surface any failure as detail
        return False, str(exc)


def lemonade_resident_loaded(
    base_url: str = "http://127.0.0.1:8001",
    model_substr: str = "gemma4",
) -> Probe:
    """resident-small is Lemonade FLM; treat any loaded gemma4-ish model as ok."""
    ok, detail = http_probe(f"{base_url}/api/v0/health", timeout=3.0)
    if not ok:
        return Probe("resident-small", f"lemonade unreachable: {detail}", False)
    # Cheap substring check without depending on full status_dashboard parse.
    loaded = model_substr.lower() in detail.lower() or "loaded" in detail.lower()
    return Probe(
        "resident-small",
        detail if loaded else f"lemonade up; may not have resident-small loaded: {detail}",
        True,  # service path ok even if model cold; warm is separate
    )


def collect_baseline_status(
    *,
    unit_active=unit_is_active,
    cont_status=container_status,
    probe_http=http_probe,
    resident=lemonade_resident_loaded,
) -> list[Probe]:
    """Ordered probes for the standing always-on closed loop."""
    rows: list[Probe] = []

    # Loop order: hear → think → speak → remember → manage
    stt = unit_active("aipc-voice-stt-sensevoice.service")
    ok_stt, stt_http = probe_http("http://127.0.0.1:9001/healthz")
    rows.append(
        Probe(
            "sensevoice",
            f"unit={stt}; health={stt_http}",
            stt == "active" and ok_stt,
        )
    )

    rows.append(resident())

    litellm_u = unit_active("litellm.service")
    ok_ll, ll_http = probe_http("http://127.0.0.1:4000/health/liveliness")
    if not ok_ll:
        ok_ll, ll_http = probe_http("http://127.0.0.1:4000/v1/models")
    rows.append(
        Probe(
            "litellm",
            f"unit={litellm_u}; health={ll_http}",
            ok_ll,
        )
    )

    chat_u = unit_active("aipc-agent-orchestrator.service")
    ok_chat, chat_http = probe_http("http://127.0.0.1:4100/healthz")
    rows.append(
        Probe(
            "chat",
            f"unit={chat_u}; health={chat_http}",
            chat_u == "active" and ok_chat,
        )
    )

    kokoro_unit = unit_active("aipc-kokoro.service")
    kokoro_ctr = cont_status(KOKORO_CONTAINER)
    ok_k, k_http = probe_http("http://127.0.0.1:8880/health")
    rows.append(
        Probe(
            "kokoro",
            f"unit={kokoro_unit}; container={kokoro_ctr}; health={k_http}",
            ok_k and (kokoro_unit == "active" or kokoro_ctr == "running"),
        )
    )

    mem0 = unit_active("aipc-mem0.service")
    ok_m, m_http = probe_http("http://127.0.0.1:7000/healthz")
    rows.append(
        Probe(
            "mem0",
            f"unit={mem0}; health={m_http}",
            mem0 == "active" and ok_m,
        )
    )

    ok_p, p_http = probe_http("http://127.0.0.1:7080/healthz")
    portal_u = unit_active("aipc-portal.service")
    rows.append(
        Probe(
            "portal",
            f"unit={portal_u}; health={p_http}",
            ok_p,
        )
    )

    # Optional peer (not required for loop).
    ok_c, c_http = probe_http("http://127.0.0.1:9880/healthz")
    rows.append(Probe("cosyvoice", c_http, ok_c))

    clone = Path("/var/lib/aipc-voice/persona/clone.wav")
    if clone.is_file():
        rows.append(Probe("clone.wav", f"present size={clone.stat().st_size}", True))
    else:
        rows.append(Probe("clone.wav", "missing (optional until Cosy clone)", True))

    # Shared UX / overlay / wake (Siri-like surface — aipc_lib.voice_ux contract)
    try:
        from aipc_lib import voice_ux as voice_ux_mod

        for name, detail, ok in voice_ux_mod.collect_ux_probes(unit_active=unit_active):
            rows.append(Probe(name, detail, ok))
    except Exception as exc:  # noqa: BLE001
        rows.append(Probe("ux-state", f"unavailable: {exc}", True))

    # Streaming turn flag (default off until hardware-verified TTFA).
    import os

    stream_on = os.environ.get("AIPC_VOICE_STREAM", "0") not in ("0", "false", "no", "")
    stream_helper = resolve_helper("stream")
    stream_ok = True  # advisory: missing binary only fails when flag is on
    if stream_on and stream_helper is None:
        stream_ok = False
    rows.append(
        Probe(
            "voice-stream",
            f"AIPC_VOICE_STREAM={'1' if stream_on else '0'}; "
            f"helper={'present' if stream_helper else 'missing'}; "
            f"chat_stream=http://127.0.0.1:4100/chat/stream",
            stream_ok,
        )
    )

    return rows


def format_status(probes: list[Probe]) -> str:
    width = max((len(p.name) for p in probes), default=8)
    lines = []
    for p in probes:
        mark = "ok" if p.ok else "!!"
        lines.append(f"{mark}  {p.name:<{width}}  {p.detail}")
    return "\n".join(lines)


def resolve_helper(name: str) -> Path | None:
    """Find a shipped aipc-voice-* helper on PATH or known install roots."""
    binary = HELPERS.get(name, name)
    which = shutil.which(binary)
    if which:
        return Path(which)
    for root in (Path("/usr/bin"), Path("/usr/local/bin"), Path.home() / ".local/bin"):
        cand = root / binary
        if cand.is_file() and os_access_x(cand):
            return cand
    return None


def os_access_x(path: Path) -> bool:
    import os

    return os.access(path, os.X_OK)


def plan_start() -> list[list[str]]:
    """Commands to bring the closed loop online (hear→think→speak→remember→UI)."""
    cmds: list[list[str]] = []
    for unit in (
        "lemonade.service",
        "litellm.service",
        "aipc-mem0.service",
        "aipc-agent-orchestrator.service",
        "aipc-voice-stt-sensevoice.service",
        "aipc-kokoro.service",
        "aipc-portal.service",
    ):
        cmds.append(["systemctl", "start", unit])
    # Live hosts may only have a free-running container (no quadlet unit yet).
    cmds.append(["podman", "start", KOKORO_CONTAINER])
    return cmds


def plan_stop() -> list[list[str]]:
    """Stop voice STT/TTS only. mem0 stays (shared with text agents).

    Stopping mem0 would break non-voice consumers; resident-small is NPU LLM
    and is never stopped here.
    """
    return [
        ["systemctl", "stop", "aipc-voice-stt-sensevoice.service"],
        ["systemctl", "stop", "aipc-kokoro.service"],
        ["podman", "stop", KOKORO_CONTAINER],
    ]


def run_cmd(argv: list[str], *, sudo: bool = False, runner=subprocess.run) -> subprocess.CompletedProcess:
    cmd = (["sudo", "-n"] + argv) if sudo else argv
    return runner(cmd, capture_output=True, text=True, check=False)


def apply_plan(
    cmds: list[list[str]],
    *,
    dry_run: bool = False,
    sudo: bool = True,
    runner=subprocess.run,
) -> list[tuple[list[str], int, str]]:
    """Run start/stop plan; tolerate missing units/containers (returncode != 0)."""
    results: list[tuple[list[str], int, str]] = []
    for argv in cmds:
        if dry_run:
            results.append((argv, 0, "dry-run"))
            continue
        # systemctl usually needs root; podman may be rootful or rootless.
        need_sudo = sudo and argv[0] == "systemctl"
        proc = run_cmd(argv, sudo=need_sudo, runner=runner)
        msg = (proc.stderr or proc.stdout or "").strip()
        results.append((argv, proc.returncode, msg))
    return results
