# AIPC Voice Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the voice AIPC assistant in staged slices: daily-usable v0 push-to-talk, then TTS fallback, then full Phase 3 wake/mute/routing gated by hardware verification.

**Architecture:** Keep the existing `aipc-voice-once` one-shot path as the stable core. Add a small runtime hotkey installer, a small doctor helper layer, and a small TTS client/router around it before touching wake-word or streaming orchestration. Full wake-word and mute behavior remains under `openspec/changes/phase-3-voice` and is marked complete only after physical Strix Halo verification.

**Tech Stack:** Python stdlib for CLI helpers, POSIX shell for module verify scripts, KDE Plasma `kglobalaccel`/`kwriteconfig6` where available, systemd units/targets, existing `aipc_lib.doctor.Result`, existing module render pipeline, LiteLLM/agent-orchestrator HTTP endpoints.

## Global Constraints

- Use existing `openspec/changes/phase-3-voice`; do not create a second voice change.
- LLM calls from voice modules go through agent-orchestrator/LiteLLM, never direct backend URLs.
- Do not fetch model weights or start services from `post-install.sh`.
- Do not hardcode the primary username into installed module files.
- Runtime/microphone/desktop checks are `OPTIONAL` or `WARN` unless the installed file is missing or syntactically broken.
- Keep `notify-send` text fallback even after TTS lands.
- Commit messages must include this trailer template when workers commit:

```text
Co-authored-by: claude-sonnet-5 <noreply@anthropic.com>
Agent-Role: 副官
Agent-Run: phase-3-voice-2026-07-08
Spec-Task: phase-3-voice#<task-id>
```

---

## File Structure

### Existing files to modify

- `modules/voice-pipecat/files/usr/bin/aipc-voice-once` — keep as the one-shot voice entry; add optional TTS dispatch in Task 4 only.
- `modules/voice-pipecat/verify.sh` — run syntax/self-tests for voice scripts and hotkey helper.
- `modules/voice-pipecat/README.md` — update current status after hotkey and TTS stages.
- `modules/voice-pipecat/post-install.sh` — install static files only; no service starts.
- `tools/aipc_lib/doctor.py` — add voice-specific checks returning `Result` objects.
- `tools/aipc_lib/cli.py` — append voice doctor results to the existing `aipc doctor` table.
- `tools/tests/test_doctor_memory_rag.py` or new `tools/tests/test_doctor_voice.py` — test doctor helpers.
- `openspec/changes/phase-3-voice/tasks.md` — mark only tasks that are actually satisfied with the achieved verification tier.

### New files to create

- `modules/voice-pipecat/files/usr/bin/aipc-voice-bind-hotkey` — runtime helper to register or print the push-to-talk binding.
- `modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_tts.py` — tiny stdlib TTS router/client used by `aipc-voice-once`.
- `docs/voice-pipeline.md` — staged voice pipeline and verification notes.
- `tools/tests/test_doctor_voice.py` — targeted tests for voice doctor checks.

---

### Task 1: Add push-to-talk hotkey helper for v0

**Files:**
- Create: `modules/voice-pipecat/files/usr/bin/aipc-voice-bind-hotkey`
- Modify: `modules/voice-pipecat/verify.sh`
- Modify: `modules/voice-pipecat/README.md`
- Modify: `openspec/changes/phase-3-voice/tasks.md`

**Interfaces:**
- Consumes: executable `/usr/bin/aipc-voice-once`
- Produces: executable `/usr/bin/aipc-voice-bind-hotkey` with `--self-test`, `--dry-run`, and default command `/usr/bin/aipc-voice-once`

- [ ] **Step 1: Write the helper with offline self-test**

Create `modules/voice-pipecat/files/usr/bin/aipc-voice-bind-hotkey`:

```python
#!/usr/bin/env python3
"""Bind AIPC voice push-to-talk in the current desktop session."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_SHORTCUT = "Meta+Space"
DEFAULT_COMMAND = "/usr/bin/aipc-voice-once"
ACTION_ID = "aipc-voice-once"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shortcut", default=DEFAULT_SHORTCUT)
    parser.add_argument("--command", default=DEFAULT_COMMAND)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def _commands(shortcut: str, command: str) -> list[list[str]]:
    desktop = Path.home() / ".local/share/applications/aipc-voice-once.desktop"
    desktop_text = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=AIPC Voice Assistant\n"
        f"Exec={command}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
    )
    return [
        ["install-desktop", str(desktop), desktop_text],
        [
            "kwriteconfig6",
            "--file",
            "kglobalshortcutsrc",
            "--group",
            "services",
            "--key",
            "aipc-voice-once.desktop",
            f"{shortcut},none,AIPC Voice Assistant",
        ],
        ["qdbus6", "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel.reloadConfig"],
    ]


def _apply_desktop_file(path: str, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _run(cmd: list[str]) -> None:
    if cmd[0] == "install-desktop":
        _apply_desktop_file(cmd[1], cmd[2])
        return
    subprocess.run(cmd, check=True)


def _missing_tools() -> list[str]:
    return [name for name in ("kwriteconfig6", "qdbus6") if shutil.which(name) is None]


def _self_test() -> int:
    cmds = _commands(DEFAULT_SHORTCUT, DEFAULT_COMMAND)
    assert cmds[0][0] == "install-desktop"
    assert "aipc-voice-once.desktop" in cmds[1]
    assert DEFAULT_SHORTCUT in cmds[1][-1]
    print("aipc-voice-bind-hotkey: self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()

    missing = _missing_tools()
    cmds = _commands(args.shortcut, args.command)
    if args.dry_run or missing or not os.environ.get("DISPLAY"):
        for cmd in cmds:
            if cmd[0] == "install-desktop":
                print(f"write {cmd[1]}")
            else:
                print(" ".join(cmd))
        if missing:
            print(f"aipc-voice-bind-hotkey: missing desktop tools: {', '.join(missing)}", file=sys.stderr)
            return 2
        if not os.environ.get("DISPLAY"):
            print("aipc-voice-bind-hotkey: DISPLAY is not set; run inside the desktop session", file=sys.stderr)
            return 2
        return 0

    for cmd in cmds:
        _run(cmd)
    print(f"aipc-voice-bind-hotkey: bound {args.shortcut} to {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Make the helper executable**

Run:

```bash
chmod +x modules/voice-pipecat/files/usr/bin/aipc-voice-bind-hotkey
```

Expected: no output and executable bit set.

- [ ] **Step 3: Extend module verification**

Update `modules/voice-pipecat/verify.sh` so it checks both scripts:

```sh
#!/bin/sh
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

voice_once="$this_dir/files/usr/bin/aipc-voice-once"
hotkey="$this_dir/files/usr/bin/aipc-voice-bind-hotkey"

python3 -c "import ast; ast.parse(open('$voice_once').read())" || {
    echo "voice-pipecat: aipc-voice-once syntax error" >&2
    exit 1
}
python3 "$voice_once" --self-test >/dev/null || {
    echo "voice-pipecat: aipc-voice-once self-test failed" >&2
    exit 1
}
python3 -c "import ast; ast.parse(open('$hotkey').read())" || {
    echo "voice-pipecat: aipc-voice-bind-hotkey syntax error" >&2
    exit 1
}
python3 "$hotkey" --self-test >/dev/null || {
    echo "voice-pipecat: aipc-voice-bind-hotkey self-test failed" >&2
    exit 1
}

exit 0
```

- [ ] **Step 4: Run the module check**

Run:

```bash
modules/voice-pipecat/verify.sh
```

Expected: exit code `0`.

- [ ] **Step 5: Update README status**

In `modules/voice-pipecat/README.md`, change the current-status paragraph to say v0 has a runtime hotkey helper but no wake word and no guaranteed TTS yet. Add this command block:

```markdown
Bind the push-to-talk shortcut from a desktop session:

```bash
aipc-voice-bind-hotkey
```

If KDE tools or `DISPLAY` are unavailable, the helper prints the commands it would run and exits optional (`2`) instead of changing system state.
```

- [ ] **Step 6: Update OpenSpec tasks for real scope only**

In `openspec/changes/phase-3-voice/tasks.md`, annotate task 7.1 or the existing hotkey/deferred line with this exact evidence style:

```markdown
- [x] 7.1 Runtime push-to-talk binding helper exists as `aipc-voice-bind-hotkey`; static-verified only. Full desktop hotkey behavior remains hardware/manual-session verification.
```

Do not mark wake-word or TTS tasks complete in this task.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add modules/voice-pipecat openspec/changes/phase-3-voice/tasks.md
git commit -m "feat(voice): add push-to-talk hotkey helper"
```

Expected: commit succeeds with project trailers added to the message.

---

### Task 2: Add voice doctor checks

**Files:**
- Modify: `tools/aipc_lib/doctor.py`
- Modify: `tools/aipc_lib/cli.py`
- Create: `tools/tests/test_doctor_voice.py`
- Modify: `openspec/changes/phase-3-voice/tasks.md`

**Interfaces:**
- Consumes: `doctor.Result(module: str, status: str, message: str)` and status constants from `tools/aipc_lib/doctor.py`
- Produces: `doctor.check_voice_once(...) -> list[Result]`

- [ ] **Step 1: Add failing tests**

Create `tools/tests/test_doctor_voice.py`:

```python
from pathlib import Path

from aipc_lib import doctor


class _FakeCompletedProcess:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_check_voice_once_fails_when_script_missing(tmp_path: Path) -> None:
    results = doctor.check_voice_once(script=tmp_path / "missing")
    assert results == [
        doctor.Result(
            module="voice-pipecat",
            status=doctor.STATUS_FAIL,
            message=f"{tmp_path / 'missing'} missing or not executable",
        )
    ]


def test_check_voice_once_reports_optional_stt_unit_missing(tmp_path: Path) -> None:
    script = tmp_path / "aipc-voice-once"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)

    results = doctor.check_voice_once(
        script=script,
        stt_unit=tmp_path / "aipc-voice-stt-sensevoice.service",
        notifier="definitely-notify-send-missing",
        runner=lambda *a, **k: _FakeCompletedProcess(3),
    )

    assert results[0] == doctor.Result("voice-pipecat", doctor.STATUS_OK, f"{script} executable")
    assert results[1].module == "voice-stt-sensevoice"
    assert results[1].status == doctor.STATUS_OPTIONAL
    assert "unit not installed" in results[1].message
    assert results[2] == doctor.Result(
        "voice-pipecat-notify",
        doctor.STATUS_WARN,
        "notify-send not found; replies fall back to stdout",
    )


def test_check_voice_once_reports_active_stt_unit(tmp_path: Path) -> None:
    script = tmp_path / "aipc-voice-once"
    unit = tmp_path / "aipc-voice-stt-sensevoice.service"
    script.write_text("#!/bin/sh\nexit 0\n")
    unit.write_text("[Service]\nExecStart=/bin/true\n")
    script.chmod(0o755)

    results = doctor.check_voice_once(
        script=script,
        stt_unit=unit,
        notifier="sh",
        runner=lambda *a, **k: _FakeCompletedProcess(0),
    )

    assert doctor.Result("voice-stt-sensevoice", doctor.STATUS_OK, "aipc-voice-stt-sensevoice.service active") in results
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=tools pytest tools/tests/test_doctor_voice.py -q
```

Expected: FAIL because `doctor.check_voice_once` is not defined.

- [ ] **Step 3: Implement doctor helper**

Add to `tools/aipc_lib/doctor.py` after `check_vector_count`:

```python

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
        proc = runner(["systemctl", "is-active", "--quiet", stt_unit.stem], check=False)
        status = STATUS_OK if proc.returncode == 0 else STATUS_OPTIONAL
        message = f"{stt_unit.stem} active" if proc.returncode == 0 else f"{stt_unit.stem} installed but not active"
        results.append(Result("voice-stt-sensevoice", status, message))

    if shutil.which(notifier) is None:
        results.append(Result("voice-pipecat-notify", STATUS_WARN, "notify-send not found; replies fall back to stdout"))
    else:
        results.append(Result("voice-pipecat-notify", STATUS_OK, "notify-send available"))

    return results
```

Also add the import near the top:

```python
import shutil
```

- [ ] **Step 4: Wire checks into CLI doctor table**

In `tools/aipc_lib/cli.py`, inside `doctor()` after vector checks are appended, add:

```python
    results.extend(doctor_mod.check_voice_once())
```

The surrounding pattern should remain the same: results are later displayed and any `STATUS_FAIL` sets exit code `1`.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
PYTHONPATH=tools pytest tools/tests/test_doctor_voice.py tools/tests/test_doctor_memory_rag.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Run CLI smoke check**

Run:

```bash
PYTHONPATH=tools python -m aipc_lib.cli doctor
```

Expected: command prints an `aipc doctor` table. On a non-installed checkout, voice may show `FAIL` for `/usr/bin/aipc-voice-once`; that is acceptable for this smoke check only if the command reaches the table without a traceback.

- [ ] **Step 7: Update OpenSpec tasks**

In `openspec/changes/phase-3-voice/tasks.md`, mark doctor static checks complete with render/static wording:

```markdown
- [x] 8.1 `aipc doctor` includes static voice checks for `aipc-voice-once`, SenseVoice unit install/activity, and notifier fallback.
- [x] 8.2 Desktop/microphone/runtime readiness is reported as optional/warn instead of render-time failure.
```

- [ ] **Step 8: Commit Task 2**

Run:

```bash
git add tools/aipc_lib/doctor.py tools/aipc_lib/cli.py tools/tests/test_doctor_voice.py openspec/changes/phase-3-voice/tasks.md
git commit -m "feat(doctor): report voice assistant readiness"
```

Expected: commit succeeds with project trailers.

---

### Task 3: Document the staged voice pipeline

**Files:**
- Create: `docs/voice-pipeline.md`
- Modify: `docs/architecture.md`
- Modify: `modules/voice-pipecat/README.md`
- Modify: `openspec/changes/phase-3-voice/tasks.md`

**Interfaces:**
- Consumes: design doc `docs/superpowers/specs/2026-07-08-aipc-voice-assistant-design.md`
- Produces: user-facing document describing current v0 commands, fallback behavior, and verification tiers

- [ ] **Step 1: Create the pipeline doc**

Create `docs/voice-pipeline.md`:

```markdown
# Voice Pipeline

The voice assistant is implemented in staged slices. The current reliable core is a one-shot push-to-talk command; wake word, TTS, and full streaming behavior are layered on top only after their services are verified.

## Stage 1: v0 push-to-talk text-out

```text
push-to-talk or manual command
        │
        ▼
aipc-voice-once
        │
        ├── arecord captures 16 kHz mono WAV
        ├── POST http://127.0.0.1:9001/transcribe
        ├── POST http://127.0.0.1:4100/chat
        └── notify-send text reply, stdout fallback
```

Run manually:

```bash
aipc-voice-once --seconds 5
```

Bind the KDE push-to-talk helper from inside the desktop session:

```bash
aipc-voice-bind-hotkey
```

If KDE global-shortcut tools are missing or no desktop session is active, the helper prints the commands it would run and exits optional.

## Stage 2: TTS output

When TTS services are available, `aipc-voice-once` may speak the assistant reply. Text notification remains the fallback so a TTS failure does not break the assistant.

## Stage 3: Full Phase 3

Full Phase 3 adds wake-word inference, listen-off mute triggers, command-vs-chat routing, firstboot persona/wake screens, and hardware verification on the Strix Halo machine.

## Verification tiers

- Static: script syntax, self-tests, and targeted Python tests pass.
- Render-verified: both bootc and ansible renders produce the expected files.
- Hardware-verified: microphone capture, STT, agent `/chat`, notification or audio output, and desktop hotkey are exercised on the physical AI PC.

Do not treat render-verified as hardware-verified for microphone, TTS, wake word, or desktop hotkey behavior.
```

- [ ] **Step 2: Link from architecture docs**

In `docs/architecture.md`, find the Phase 3 voice row or section and add one sentence:

```markdown
Voice pipeline details and current staged verification status live in `docs/voice-pipeline.md`.
```

- [ ] **Step 3: Link from module README**

In `modules/voice-pipecat/README.md`, add:

```markdown
See `docs/voice-pipeline.md` for the staged end-to-end flow and verification tiers.
```

- [ ] **Step 4: Update OpenSpec docs task**

In `openspec/changes/phase-3-voice/tasks.md`, mark the docs task complete only for the staged doc:

```markdown
- [x] 9.2 `docs/voice-pipeline.md` documents the staged v0/PTT, TTS fallback, and full Phase 3 path with verification tiers.
```

- [ ] **Step 5: Run markdown/link smoke checks**

Run:

```bash
test -s docs/voice-pipeline.md
grep -R "docs/voice-pipeline.md" docs/architecture.md modules/voice-pipecat/README.md
```

Expected: both commands exit `0`; grep prints two matching lines.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add docs/voice-pipeline.md docs/architecture.md modules/voice-pipecat/README.md openspec/changes/phase-3-voice/tasks.md
git commit -m "docs(voice): document staged assistant pipeline"
```

Expected: commit succeeds with project trailers.

---

### Task 4: Add TTS router with text fallback

**Files:**
- Create: `modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_tts.py`
- Modify: `modules/voice-pipecat/files/usr/bin/aipc-voice-once`
- Modify: `modules/voice-pipecat/verify.sh`
- Modify: `modules/voice-pipecat/README.md`
- Modify: `openspec/changes/phase-3-voice/tasks.md`

**Interfaces:**
- Consumes: assistant reply text from `aipc-voice-once.show(reply)`
- Produces: `speak_or_notify(text: str) -> bool`; returns `True` when TTS succeeds, `False` when caller should use existing text notification

- [ ] **Step 1: Create TTS helper with self-test**

Create `modules/voice-pipecat/files/usr/lib/aipc-voice/aipc_voice_tts.py`:

```python
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

COSYVOICE_URL = os.environ.get("AIPC_COSYVOICE_URL", "http://127.0.0.1:9880/tts")
KOKORO_URL = os.environ.get("AIPC_KOKORO_URL", "http://127.0.0.1:8880/v1/audio/speech")
TTS_TIMEOUT = float(os.environ.get("AIPC_TTS_TIMEOUT", "8"))

_CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")


def choose_tts_url(text: str) -> str:
    return COSYVOICE_URL if _CJK_RE.search(text) else KOKORO_URL


def build_payload(text: str, url: str) -> tuple[bytes, str]:
    if url == KOKORO_URL:
        return json.dumps({"model": "kokoro", "voice": "af_heart", "input": text}).encode(), "application/json"
    return json.dumps({"text": text}).encode(), "application/json"


def speak(text: str, opener=urllib.request.urlopen) -> bool:
    url = choose_tts_url(text)
    body, content_type = build_payload(text, url)
    req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="POST")
    try:
        with opener(req, timeout=TTS_TIMEOUT) as resp:
            resp.read()
        return True
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def _self_test() -> int:
    assert choose_tts_url("你好") == COSYVOICE_URL
    assert choose_tts_url("hello") == KOKORO_URL
    body, content_type = build_payload("hello", KOKORO_URL)
    assert content_type == "application/json"
    assert json.loads(body.decode())["input"] == "hello"
    print("aipc_voice_tts: self-test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
```

- [ ] **Step 2: Wire TTS into `aipc-voice-once` without breaking text fallback**

In `modules/voice-pipecat/files/usr/bin/aipc-voice-once`, add imports near the top:

```python
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib/aipc-voice"))
try:
    import aipc_voice_tts
except Exception:
    aipc_voice_tts = None
```

Replace the existing `show(reply)` function with:

```python
def show(reply):
    """Speak the reply when TTS is ready; always keep text fallback."""
    if os.environ.get("AIPC_VOICE_TTS", "1") != "0" and aipc_voice_tts is not None:
        if aipc_voice_tts.speak(reply):
            return
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "AIPC Assistant", reply], check=False)
    else:
        print(f"aipc-voice-once: (notify-send unavailable) reply: {reply}")
```

Extend `_self_test()` with:

```python
    assert os.environ.get("AIPC_VOICE_TTS", "1") in ("0", "1")
```

- [ ] **Step 3: Extend verify script for TTS helper**

In `modules/voice-pipecat/verify.sh`, add after hotkey checks:

```sh
tts="$this_dir/files/usr/lib/aipc-voice/aipc_voice_tts.py"
python3 -c "import ast; ast.parse(open('$tts').read())" || {
    echo "voice-pipecat: aipc_voice_tts syntax error" >&2
    exit 1
}
python3 "$tts" >/dev/null || {
    echo "voice-pipecat: aipc_voice_tts self-test failed" >&2
    exit 1
}
```

- [ ] **Step 4: Run module verification**

Run:

```bash
modules/voice-pipecat/verify.sh
```

Expected: exit code `0`.

- [ ] **Step 5: Update README and tasks**

In `modules/voice-pipecat/README.md`, add:

```markdown
TTS is opportunistic. Set `AIPC_VOICE_TTS=0` to force text-only output. If local TTS endpoints are unavailable, `aipc-voice-once` keeps the existing `notify-send` or stdout fallback.
```

In `openspec/changes/phase-3-voice/tasks.md`, mark only router/fallback scope:

```markdown
- [x] 4.3 Minimal language router exists in `aipc_voice_tts.py`; spoken output remains hardware-gated until local TTS services are active and tested.
```

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add modules/voice-pipecat openspec/changes/phase-3-voice/tasks.md
git commit -m "feat(voice): add opportunistic TTS fallback"
```

Expected: commit succeeds with project trailers.

---

### Task 5: Render and static verification pass

**Files:**
- Modify: `openspec/changes/phase-3-voice/tasks.md`
- Read/check only: generated render outputs

**Interfaces:**
- Consumes: Tasks 1-4 completed
- Produces: static/render verification evidence for the voice assistant slices

- [ ] **Step 1: Run targeted Python tests**

Run:

```bash
PYTHONPATH=tools pytest tools/tests/test_doctor_voice.py tools/tests/test_doctor_memory_rag.py -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run voice module verify scripts**

Run:

```bash
modules/voice-pipecat/verify.sh
modules/voice-stt-sensevoice/verify.sh
```

Expected: `voice-pipecat` exits `0`; `voice-stt-sensevoice` exits `0` with static OK on non-installed hosts or hardware OK on the AI PC.

- [ ] **Step 3: Run OpenSpec validation**

Run:

```bash
npx -y @fission-ai/openspec validate phase-3-voice --strict
```

Expected: validation PASS. If it fails because task wording was changed without a spec delta mismatch, fix the tasks/spec wording rather than bypassing validation.

- [ ] **Step 4: Run bootc render**

Run:

```bash
tools/aipc render bootc
```

Expected: command exits `0`; generated Containerfile includes `voice-pipecat` files.

- [ ] **Step 5: Run ansible render check**

Run:

```bash
tools/aipc render ansible --check
```

Expected: command exits `0`.

- [ ] **Step 6: Update verification notes in tasks**

In `openspec/changes/phase-3-voice/tasks.md`, mark local verification subtasks complete only for commands that actually passed:

```markdown
- [x] 10.1 `tools/aipc render bootc` passed for staged voice assistant files.
- [x] 10.2 `tools/aipc render ansible --check` passed for staged voice assistant files.
- [x] 12.1 `npx -y @fission-ai/openspec validate phase-3-voice --strict` passed after staged updates.
```

Do not mark hardware tasks `11.x` complete unless they were run on the AI PC.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add openspec/changes/phase-3-voice/tasks.md
git commit -m "test(voice): record staged verification"
```

Expected: commit succeeds with project trailers.

---

### Task 6: Hardware verification checklist and final handoff

**Files:**
- Modify: `docs/voice-pipeline.md`
- Modify: `openspec/changes/phase-3-voice/tasks.md`
- Modify: `docs/agent-log.md`

**Interfaces:**
- Consumes: render-verified staged voice assistant
- Produces: clear evidence of what is hardware-verified and what remains future Phase 3 scope

- [ ] **Step 1: Run hardware commands on physical Strix Halo only**

Run on the target machine after deployment:

```bash
systemctl is-active aipc-voice-stt-sensevoice.service
aipc-voice-once --seconds 5
aipc-voice-bind-hotkey --dry-run
aipc doctor
```

Expected:

- STT service is active or reported with a clear service error.
- `aipc-voice-once` records, transcribes, reaches `/chat`, and returns text or speech.
- Hotkey helper either binds from the desktop session or prints the exact commands needed.
- `aipc doctor` reports voice rows without traceback.

- [ ] **Step 2: Update hardware verification status**

If the hardware commands pass, add this section to `docs/voice-pipeline.md`:

```markdown
## Hardware verification

Verified on the physical Strix Halo AI PC on 2026-07-08:

- `aipc-voice-once --seconds 5` completed a microphone -> STT -> `/chat` -> reply round trip.
- `aipc doctor` reported voice readiness rows without traceback.
- Push-to-talk helper was exercised from the desktop session.

Wake word, listen-off triggers, and firstboot voice screens remain unverified until their implementation tasks land.
```

If any item fails, write the failing command and one-line failure instead of the success bullets.

- [ ] **Step 3: Update OpenSpec hardware tasks honestly**

If hardware passed, mark only the matching `11.x` items. Use this exact style:

```markdown
- [x] 11.6 PTT helper exercised on physical AI PC; verified tier: hardware.
```

Leave wake-word, lock/DND mute, and full chat routing tasks unchecked unless those exact paths were exercised.

- [ ] **Step 4: Append agent log row**

Append one row to `docs/agent-log.md`:

```markdown
| 2026-07-08 | 副官 | claude-sonnet-5 | phase-3-voice-2026-07-08 | phase-3-voice#7.1,#8.1,#8.2,#9.2,#10.1,#10.2,#12.1 | <sha-range> | staged voice assistant PTT/doctor/docs/TTS fallback; hardware status recorded | 
```

Replace `<sha-range>` with the actual range from `git log --oneline` after commits.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add docs/voice-pipeline.md openspec/changes/phase-3-voice/tasks.md docs/agent-log.md
git commit -m "docs(voice): record staged verification status"
```

Expected: commit succeeds with project trailers.

---

## Self-Review

Spec coverage:

- Daily-usable v0 PTT: Task 1.
- Voice doctor checks: Task 2.
- Documentation: Task 3.
- TTS with text fallback: Task 4.
- Static/render/OpenSpec verification: Task 5.
- Hardware verification boundary: Task 6.
- Full wake-word/mute/routing remains explicitly hardware-gated and is not falsely marked complete.

Placeholder scan:

- This plan contains no `TBD`, no vague edge-case step, and every code-changing step includes concrete code or exact text.

Type/interface consistency:

- `doctor.check_voice_once(...) -> list[Result]` is defined in Task 2 before CLI use.
- `aipc_voice_tts.speak(text) -> bool` is defined in Task 4 before `aipc-voice-once.show()` calls it.
- Hotkey helper `--self-test` is defined in Task 1 before `verify.sh` invokes it.
