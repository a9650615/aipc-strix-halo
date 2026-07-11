"""Voice assistant template packs (identity + TTS routing knobs).

Layout (runtime):
  /var/lib/aipc-voice/persona/templates/<id>/
    manifest.json   # id, name, description, tags, system, mode, tts_prefer, ...
    clone.wav
    clone.txt
  /var/lib/aipc-voice/persona/active.json   # currently applied template
  /var/lib/aipc-voice/persona/clone.wav     # active CosyVoice prompt (compat)

CosyVoice keeps reading clone.wav; apply() copies the pack there and writes
active.json so the server can pick up system/mode without a restart.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

PERSONA = Path(os.environ.get("AIPC_PERSONA_DIR", "/var/lib/aipc-voice/persona"))
TEMPLATES = PERSONA / "templates"
ACTIVE = PERSONA / "active.json"
CLONE_WAV = PERSONA / "clone.wav"
CLONE_TXT = PERSONA / "clone.txt"
PREFER_COSY = Path(
    os.environ.get("AIPC_PREFER_COSYVOICE_FILE", "/etc/aipc/voice/prefer-cosyvoice")
)
TTS_ZH_VOICE = Path(os.environ.get("AIPC_TTS_ZH_VOICE_FILE", "/etc/aipc/voice/tts-zh-voice"))
TTS_EN_VOICE = Path(os.environ.get("AIPC_TTS_EN_VOICE_FILE", "/etc/aipc/voice/tts-en-voice"))

MANIFEST_NAME = "manifest.json"
REQUIRED_KEYS = ("id", "name")


def _install(src: Path, dest: Path, mode: int = 0o644) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dest)
        os.chmod(dest, mode)
    except PermissionError:
        subprocess.run(
            ["sudo", "install", "-D", f"-m{mode:o}", str(src), str(dest)],
            check=True,
        )


def _write_text(dest: Path, text: str, mode: int = 0o644) -> None:
    data = text if text.endswith("\n") else text + "\n"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(data, encoding="utf-8")
        os.chmod(dest, mode)
    except PermissionError:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["sudo", "install", "-D", f"-m{mode:o}", tmp_path, str(dest)],
                check=True,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)


def _write_json(dest: Path, obj: dict[str, Any], mode: int = 0o644) -> None:
    _write_text(dest, json.dumps(obj, ensure_ascii=False, indent=2) + "\n", mode=mode)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def template_dir(template_id: str) -> Path:
    tid = (template_id or "").strip()
    if not tid or "/" in tid or tid in (".", ".."):
        raise ValueError(f"invalid template id: {template_id!r}")
    return TEMPLATES / tid


def default_manifest(template_id: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": template_id,
        "name": template_id,
        "description": "",
        "tags": [],
        "tts_prefer": "cosyvoice",  # cosyvoice | kokoro
        "mode": "zero_shot",  # zero_shot | instruct2
        "system": "You are a helpful assistant.",
        "instruct": "",
        "kokoro_voice_zh": "",
        "kokoro_voice_en": "",
        "notes": "",
    }
    base.update({k: v for k, v in extra.items() if v is not None})
    return base


def load_manifest(template_id: str) -> dict[str, Any]:
    d = template_dir(template_id)
    mpath = d / MANIFEST_NAME
    if not mpath.is_file():
        raise FileNotFoundError(f"template not found: {template_id} ({mpath})")
    man = _read_json(mpath)
    if man.get("id") != template_id:
        man["id"] = template_id
    return man


def list_templates() -> list[dict[str, Any]]:
    if not TEMPLATES.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for child in sorted(TEMPLATES.iterdir()):
        if not child.is_dir():
            continue
        mpath = child / MANIFEST_NAME
        if not mpath.is_file():
            continue
        try:
            man = _read_json(mpath)
        except (OSError, json.JSONDecodeError):
            continue
        man.setdefault("id", child.name)
        man["_path"] = str(child)
        man["_has_wav"] = (child / "clone.wav").is_file()
        man["_has_txt"] = (child / "clone.txt").is_file()
        rows.append(man)
    return rows


def current() -> dict[str, Any] | None:
    if not ACTIVE.is_file():
        return None
    try:
        return _read_json(ACTIVE)
    except (OSError, json.JSONDecodeError):
        return None


def save_template(
    template_id: str,
    *,
    wav: Path | None = None,
    transcript: str | None = None,
    name: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
    system: str | None = None,
    mode: str = "zero_shot",
    tts_prefer: str = "cosyvoice",
    instruct: str = "",
    kokoro_voice_zh: str = "",
    kokoro_voice_en: str = "",
    notes: str = "",
    from_current: bool = False,
) -> Path:
    """Create/update a template pack on disk."""
    d = template_dir(template_id)
    d.mkdir(parents=True, exist_ok=True)

    src_wav = CLONE_WAV if from_current else wav
    if src_wav is None:
        raise ValueError("wav path required (or from_current=True)")
    src_wav = Path(src_wav)
    if not src_wav.is_file():
        raise FileNotFoundError(f"clone wav not found: {src_wav}")

    dest_wav = d / "clone.wav"
    _install(src_wav, dest_wav)

    if transcript is None and from_current and CLONE_TXT.is_file():
        transcript = CLONE_TXT.read_text(encoding="utf-8")
    if transcript is None:
        sibling = src_wav.with_suffix(".txt")
        if sibling.is_file():
            transcript = sibling.read_text(encoding="utf-8")
    if transcript is None:
        transcript = ""
    _write_text(d / "clone.txt", transcript.strip())

    man = default_manifest(
        template_id,
        name=name or template_id,
        description=description,
        tags=tags or [],
        system=system if system is not None else "You are a helpful assistant.",
        mode=mode,
        tts_prefer=tts_prefer,
        instruct=instruct,
        kokoro_voice_zh=kokoro_voice_zh,
        kokoro_voice_en=kokoro_voice_en,
        notes=notes,
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    _write_json(d / MANIFEST_NAME, man)
    return d


def apply_template(template_id: str) -> dict[str, Any]:
    """Activate a template: copy clone files + write active.json + optional knobs."""
    man = load_manifest(template_id)
    d = template_dir(template_id)
    wav = d / "clone.wav"
    txt = d / "clone.txt"
    if not wav.is_file():
        raise FileNotFoundError(f"template {template_id} missing clone.wav")

    _install(wav, CLONE_WAV)
    if txt.is_file():
        _install(txt, CLONE_TXT)
    else:
        _write_text(CLONE_TXT, "")

    prefer = (man.get("tts_prefer") or "cosyvoice").strip().lower()
    if prefer in ("cosyvoice", "kokoro"):
        prefer_val = "1" if prefer == "cosyvoice" else "0"
        try:
            _write_text(PREFER_COSY, prefer_val)
        except Exception:
            pass

    zh = (man.get("kokoro_voice_zh") or "").strip()
    if zh:
        try:
            _write_text(TTS_ZH_VOICE, zh)
        except Exception:
            pass
    en = (man.get("kokoro_voice_en") or "").strip()
    if en:
        try:
            _write_text(TTS_EN_VOICE, en)
        except Exception:
            pass

    active = {
        "template": template_id,
        "name": man.get("name") or template_id,
        "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": (man.get("mode") or "zero_shot").strip().lower(),
        "system": man.get("system") or "You are a helpful assistant.",
        "instruct": man.get("instruct") or "",
        "tts_prefer": prefer,
        "clone_wav": str(CLONE_WAV),
        "manifest": str(d / MANIFEST_NAME),
    }
    _write_json(ACTIVE, active)
    return active


def active_overrides() -> dict[str, str]:
    """Values CosyVoice / TTS should prefer from the active template."""
    cur = current()
    if not cur:
        return {}
    out: dict[str, str] = {}
    if cur.get("system"):
        out["system"] = str(cur["system"])
    if cur.get("mode"):
        out["mode"] = str(cur["mode"]).strip().lower()
    if cur.get("instruct"):
        out["instruct"] = str(cur["instruct"])
    return out
