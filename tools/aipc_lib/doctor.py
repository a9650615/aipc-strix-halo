from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from aipc_lib.models import DEFAULT_MANIFEST, load_manifest
from aipc_lib.modules import Module

LITELLM_DEFAULT_ENDPOINT = "http://127.0.0.1:4000"
DEFAULT_BACKEND_FILE = Path("/etc/aipc/memory/backend")
VECTOR_COUNT_WARN_THRESHOLD = 1_000_000
_BACKEND_SERVICES = {"pgvector": "postgres.service", "qdrant": "qdrant.service"}

STATUS_OK = "OK"
STATUS_OPTIONAL = "OPTIONAL"
STATUS_FAIL = "FAIL"
STATUS_WARN = "WARN"


@dataclass
class Result:
    module: str
    status: str  # STATUS_OK | STATUS_OPTIONAL | STATUS_FAIL | STATUS_WARN
    message: str

    @property
    def ok(self) -> bool:
        # ponytail: back-compat shim; callers (CLI) still branch on ok
        return self.status in (STATUS_OK, STATUS_OPTIONAL, STATUS_WARN)


def run_all(mods: list[Module]) -> list[Result]:
    results: list[Result] = []
    for m in mods:
        verify = m.path / "verify.sh"
        if not verify.exists():
            results.append(Result(module=m.name, status=STATUS_OK, message="no verify.sh; skipped"))
            continue
        proc = subprocess.run(
            ["/bin/sh", str(verify)],
            capture_output=True,
            text=True,
        )
        msg = (proc.stdout + proc.stderr).strip()
        if proc.returncode == 0:
            results.append(Result(module=m.name, status=STATUS_OK, message=msg or "ok"))
        elif proc.returncode == 2:
            # ponytail: exit 2 = intentionally disabled optional module (e.g. llm-vllm)
            results.append(
                Result(module=m.name, status=STATUS_OPTIONAL, message=msg or "disabled (optional)")
            )
        else:
            results.append(Result(module=m.name, status=STATUS_FAIL, message=msg or "failed"))
    return results


def check_gateway_aliases(
    manifest_path: Path = DEFAULT_MANIFEST,
    endpoint: str = LITELLM_DEFAULT_ENDPOINT,
) -> Result | None:
    """Compare models.yaml aliases against LiteLLM /v1/models.

    Returns None if the manifest doesn't exist (llm-models not installed).
    Returns a WARN result if the gateway isn't reachable (not yet installed).
    Returns FAIL listing missing aliases if any are absent from the gateway.
    """
    entries = load_manifest(manifest_path)
    if not entries:
        return None

    url = f"{endpoint.rstrip('/')}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.URLError:
        # ponytail: gateway not running is a warning, not a fail — may not be installed yet
        return Result(
            module="litellm-aliases",
            status=STATUS_WARN,
            message=f"gateway unreachable at {endpoint}",
        )

    served = {item.get("id") for item in payload.get("data", []) if isinstance(item, dict)}
    missing = [e.alias for e in entries if e.alias not in served]
    if missing:
        return Result(
            module="litellm-aliases",
            status=STATUS_FAIL,
            message="missing from gateway: " + ", ".join(missing),
        )
    return Result(
        module="litellm-aliases",
        status=STATUS_OK,
        message=f"{len(entries)} aliases served",
    )


def check_active_backend(backend_file: Path = DEFAULT_BACKEND_FILE) -> Result | None:
    """Confirm whichever vector backend systemd unit is actually running
    matches `/etc/aipc/memory/backend`'s declared value.

    Returns None if the backend file doesn't exist (memory-rag not
    installed). Deployed images don't ship the repo's modules/ source tree,
    so this checks systemd unit state directly rather than module
    .disabled markers (see phase-2-memory#9.1).
    """
    if not backend_file.exists():
        return None

    declared = backend_file.read_text().strip()
    service = _BACKEND_SERVICES.get(declared)
    if service is None:
        return Result(
            module="memory-rag-backend",
            status=STATUS_FAIL,
            message=f"{backend_file} declares unknown backend {declared!r}",
        )

    proc = subprocess.run(["systemctl", "is-active", "--quiet", service], check=False)
    if proc.returncode != 0:
        return Result(
            module="memory-rag-backend",
            status=STATUS_FAIL,
            message=f"declared backend {declared!r} but {service} is not active",
        )
    return Result(module="memory-rag-backend", status=STATUS_OK, message=f"{declared} active")


def check_vector_count(
    dsn: str = "postgresql://postgres@127.0.0.1:5432/aipc",
    threshold: int = VECTOR_COUNT_WARN_THRESHOLD,
) -> Result | None:
    """INFO-level nudge toward `aipc db migrate qdrant` once pgvector's
    rag_chunks table crosses `threshold` rows (phase-2-memory#9.2).

    Returns None if Postgres isn't reachable (not installed/not running —
    same "not everything is hardware yet" reasoning as check_gateway_aliases).
    """
    try:
        import psycopg2

        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM rag_chunks")
            count = cur.fetchone()[0]
    except Exception:
        return None

    if count > threshold:
        return Result(
            module="memory-rag-vectors",
            status=STATUS_WARN,
            message=f"{count} vectors > {threshold} — consider `aipc db migrate qdrant`",
        )
    return Result(module="memory-rag-vectors", status=STATUS_OK, message=f"{count} vectors")


def check_voice_wake(
    policy_file: Path = Path("/etc/aipc/voice/wake-policy.env"),
    live_script: Path = Path("/var/lib/aipc-voice/lib/aipc_voice_wake.py"),
    ostree_script: Path = Path("/usr/lib/aipc-voice/aipc_voice_wake.py"),
    unit_name: str = "aipc-voice-wake.service",
    runner=subprocess.run,
) -> list[Result]:
    """Wake control-plane health: policy file, live path symbols, unit state."""
    results: list[Result] = []

    if not policy_file.is_file():
        results.append(
            Result(
                "voice-wake-policy",
                STATUS_WARN,
                f"{policy_file} missing — arm/thrash knobs fall back to code defaults",
            )
        )
    else:
        text = policy_file.read_text(encoding="utf-8", errors="replace")
        if "AIPC_WAKE_ALLOW_FUZZY_PROMOTE=0" not in text:
            results.append(
                Result(
                    "voice-wake-policy",
                    STATUS_WARN,
                    f"{policy_file} present but fuzzy promote not locked off",
                )
            )
        else:
            results.append(
                Result(
                    "voice-wake-policy",
                    STATUS_OK,
                    f"{policy_file} present (fuzzy promote off)",
                )
            )

    live = live_script if live_script.is_file() else None
    ostree = ostree_script if ostree_script.is_file() else None
    if live is None and ostree is None:
        results.append(
            Result(
                "voice-wake-code",
                STATUS_FAIL,
                "no aipc_voice_wake.py at /var/lib or /usr/lib",
            )
        )
        return results

    active = live or ostree
    body = active.read_text(encoding="utf-8", errors="replace")
    need = (
        "classify_wake_text",
        "decide_wake_arm",
        "miss_backoff_seconds",
        "junk_capture_action",
        "next_mode_after_empty_capture",
        "effective_wake_policy",
    )
    # Helpers may live in aipc_voice_wake.py or aipc_voice_wake_policy.py
    policy_path = active.parent / "aipc_voice_wake_policy.py"
    session_path = active.parent / "aipc_voice_session.py"
    body_all = body
    if policy_path.is_file():
        body_all += "\n" + policy_path.read_text(encoding="utf-8", errors="replace")
    missing = [n for n in need if n not in body_all]
    if "_MANGLED_WAKE" in body_all:
        results.append(
            Result(
                "voice-wake-code",
                STATUS_FAIL,
                f"{active}: still has _MANGLED_WAKE auto-arm (ghost path)",
            )
        )
    elif missing:
        results.append(
            Result(
                "voice-wake-code",
                STATUS_FAIL,
                f"{active}: missing policy helpers: {', '.join(missing)}",
            )
        )
    else:
        extra = ""
        if session_path.is_file() and "SessionState" in session_path.read_text(
            encoding="utf-8", errors="replace"
        ):
            extra = " + SessionState"
        results.append(
            Result(
                "voice-wake-code",
                STATUS_OK,
                f"{active} has anti-ghost + thrash helpers{extra}",
            )
        )

    if live and ostree:
        live_tree = live.read_text(encoding="utf-8", errors="replace")
        ostree_tree = ostree.read_text(encoding="utf-8", errors="replace")
        live_pol = live.parent / "aipc_voice_wake_policy.py"
        if live_pol.is_file():
            live_tree += live_pol.read_text(encoding="utf-8", errors="replace")
        ostree_pol = ostree.parent / "aipc_voice_wake_policy.py"
        if ostree_pol.is_file():
            ostree_tree += ostree_pol.read_text(encoding="utf-8", errors="replace")
        live_has = "miss_backoff_seconds" in live_tree
        ostree_has = "miss_backoff_seconds" in ostree_tree
        if live_has and not ostree_has:
            results.append(
                Result(
                    "voice-wake-drift",
                    STATUS_WARN,
                    "live /var/lib has thrash/anti-ghost policy; ostree /usr is stale "
                    "(bootc image rebuild needed for image-path parity)",
                )
            )

    proc = runner(
        ["systemctl", "is-enabled", "--quiet", unit_name],
        check=False,
        capture_output=True,
    )
    enabled = proc.returncode == 0
    proc_a = runner(
        ["systemctl", "is-active", "--quiet", unit_name],
        check=False,
        capture_output=True,
    )
    active_u = proc_a.returncode == 0
    if not enabled and not active_u:
        results.append(
            Result(
                "voice-wake-unit",
                STATUS_OPTIONAL,
                f"{unit_name} disabled/inactive (PTT-only / safety mode OK)",
            )
        )
    elif active_u:
        results.append(
            Result("voice-wake-unit", STATUS_OK, f"{unit_name} active")
        )
    else:
        results.append(
            Result(
                "voice-wake-unit",
                STATUS_WARN,
                f"{unit_name} enabled but not active",
            )
        )

    return results


def check_voice_once(
    script: Path = Path("/usr/bin/aipc-voice-once"),
    stt_unit: Path = Path("/etc/systemd/system/aipc-voice-stt-sensevoice.service"),
    notifier: str = "notify-send",
    runner=subprocess.run,
) -> list[Result]:
    results: list[Result] = []
    if not script.exists() or not script.is_file() or not script.stat().st_mode & 0o111:
        return [
            Result(
                module="voice-pipecat",
                status=STATUS_FAIL,
                message=f"{script} missing or not executable",
            )
        ]

    results.append(Result("voice-pipecat", STATUS_OK, f"{script} executable"))

    if not stt_unit.exists():
        results.append(
            Result(
                "voice-stt-sensevoice",
                STATUS_OPTIONAL,
                f"{stt_unit.name} unit not installed; voice STT not enabled on this host",
            )
        )
    else:
        proc = runner(["systemctl", "is-active", "--quiet", stt_unit.name], check=False)
        status = STATUS_OK if proc.returncode == 0 else STATUS_OPTIONAL
        message = (
            f"{stt_unit.name} active"
            if proc.returncode == 0
            else f"{stt_unit.name} installed but not active"
        )
        results.append(Result("voice-stt-sensevoice", status, message))

    if shutil.which(notifier) is None:
        results.append(
            Result(
                "voice-pipecat-notify",
                STATUS_WARN,
                "notify-send not found; replies fall back to stdout",
            )
        )
    else:
        results.append(Result("voice-pipecat-notify", STATUS_OK, "notify-send available"))

    return results
