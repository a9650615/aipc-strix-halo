#!/usr/bin/env python3
"""Always-on wake listener that triggers aipc-voice-once.

Modes (fast start first):
- phrase (default): energy gate → short STT → match custom phrases (low false
  positive; Chinese/English custom words without training a model).
- openwakeword: pretrained ONNX (e.g. hey_jarvis) when venv + models exist.
- energy: loudness-only fallback (higher false positives).

Mute: skip while /run/aipc/voice-mute exists (aipc-voice-mute.target).
"""
from __future__ import annotations

import argparse
import array
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

# UX status (optional — same paths as voice-once)
for _p in (
    Path("/usr/lib/aipc-voice"),
    Path("/var/lib/aipc-voice/lib"),
    Path(__file__).resolve().parent,
):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
try:
    import aipc_voice_ux as voice_ux
except Exception:
    voice_ux = None



# --- Policy + session (extracted; pure + state machine) ---
try:
    from aipc_voice_wake_policy import (  # type: ignore
        ALLOW_FUZZY_PROMOTE,
        CANDIDATE_SCORE,
        CMD_END_SILENCE_MS,
        CMD_MAX_S,
        COOLDOWN_S,
        ENERGY_FRAMES,
        ENERGY_THRESHOLD,
        FOLLOWUP_DIRECT,
        FRAME_MS,
        FUZZY_PARTICLES,
        MAX_REPROMPTS,
        MISS_BACKOFF_BASE,
        MISS_BACKOFF_CAP,
        POLICY_FILE_LOADED as _POLICY_FILE_LOADED,
        PROMOTE_SCORE,
        REPROMPT_TEXT,
        SAMPLE_RATE,
        classify_wake_text,
        decide_wake_arm,
        effective_wake_policy,
        junk_capture_action,
        miss_backoff_seconds,
        next_mode_after_empty_capture,
        phrase_hit,
        preload_wake_policy_file as _preload_wake_policy_file,
        score_wake_pcm,
        pcm_rms,
        norm_text as _norm,
    )
except ImportError:  # pragma: no cover
    from aipc_voice_wake_policy import *  # type: ignore

try:
    from aipc_voice_session import (  # type: ignore
        Session,
        SessionState,
        mic_mode,
        on_empty_capture,
        on_energy_open,
        on_followup_arm,
        on_followup_speech,
        on_ptt,
        on_submit_turn,
        on_wake_decision,
        ui_allowed,
    )
except ImportError:  # pragma: no cover
    Session = None  # type: ignore

def _ux(state: str, detail: str = "", **kw) -> None:
    if voice_ux is None:
        return
    try:
        voice_ux.announce(state, detail, **kw)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-voice-wake: ux fail: {exc}", flush=True)


def _playback_active(*, include_tts: bool = False) -> bool:
    """True when speakers likely output sound (for echo / bleed gating)."""
    if not ECHO_GATE:
        return False
    try:
        from aipc_lib.voice_audio import playback_active as _pa

        return bool(_pa(include_tts=include_tts))
    except Exception:
        pass
    try:
        import voice_audio  # type: ignore

        return bool(voice_audio.playback_active(include_tts=include_tts))
    except Exception:
        return False


def _effective_energy_thr(
    base: float, *, playback: bool, bleed_floor: float = 0.0
) -> float:
    """Raise threshold while media/TTS plays so speaker bleed is not 'speech'."""
    try:
        from aipc_lib.voice_audio import effective_energy_thr as _eet

        return float(
            _eet(
                base,
                playback=playback,
                ratio=PLAYBACK_ENERGY_RATIO,
                extra=PLAYBACK_ENERGY_EXTRA,
                bleed_floor=bleed_floor,
            )
        )
    except Exception:
        pass
    try:
        import voice_audio  # type: ignore

        return float(
            voice_audio.effective_energy_thr(
                base,
                playback=playback,
                ratio=PLAYBACK_ENERGY_RATIO,
                extra=PLAYBACK_ENERGY_EXTRA,
                bleed_floor=bleed_floor,
            )
        )
    except Exception:
        if not playback:
            return float(base)
        if bleed_floor > 0:
            return max(float(base), bleed_floor * 1.45 + 2800.0)
        return max(
            float(base) * PLAYBACK_ENERGY_RATIO,
            float(base) + PLAYBACK_ENERGY_EXTRA,
            12000.0,
        )


MUTE_FLAG = Path(os.environ.get("AIPC_VOICE_MUTE_FLAG", "/run/aipc/voice-mute"))
USER_MUTE_FLAG = Path(
    os.environ.get(
        "AIPC_VOICE_MUTE_FLAG_USER",
        str(Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "aipc-voice-mute"),
    )
)
ONCE_CMD = os.environ.get("AIPC_VOICE_ONCE", "/usr/bin/aipc-voice-once")
# Streaming turn worker (voice-streaming-turn). Default off until hardware-verified.
STREAM_CMD = os.environ.get("AIPC_VOICE_STREAM_CMD", "/usr/bin/aipc-voice-stream")
VOICE_STREAM = os.environ.get("AIPC_VOICE_STREAM", "0") not in ("0", "false", "no", "")
CAPTURE_S = float(os.environ.get("AIPC_WAKE_CAPTURE_S", "2.0"))
# Only for *complete-looking* progressive text; never for short/incomplete.
CMD_END_SILENCE_FAST_MS = int(os.environ.get("AIPC_WAKE_CMD_END_SILENCE_FAST_MS", "850"))
CMD_START_TIMEOUT_S = float(os.environ.get("AIPC_WAKE_CMD_START_TIMEOUT", "5"))
# Don't allow end-of-speech until this much speech audio is buffered.
CMD_MIN_SPEECH_MS = int(os.environ.get("AIPC_WAKE_CMD_MIN_SPEECH_MS", "700"))
# Progressive STT while user is still talking (seconds between snapshots).
PARTIAL_STT_S = float(os.environ.get("AIPC_WAKE_PARTIAL_STT_S", "0.9"))
PARTIAL_STT_MIN_S = float(os.environ.get("AIPC_WAKE_PARTIAL_STT_MIN_S", "0.7"))
# Progressive text must stay stable this long AND energy must drop (never end while still loud).
CMD_TEXT_STABLE_S = float(os.environ.get("AIPC_WAKE_CMD_TEXT_STABLE_S", "2.0"))
# Min spoken time before text_stable EOS is allowed (avoid cutting mid-sentence).
CMD_TEXT_STABLE_MIN_SPEECH_S = float(
    os.environ.get("AIPC_WAKE_CMD_TEXT_STABLE_MIN_SPEECH_S", "2.4")
)
# After a successful turn, stay open for follow-up speech without re-wake.
# Multi-turn follow-up (all turns after a reply):
# - always VAD-based close (sustained silence)
# - 2nd+ also enforces min open ≈ last TTS length (+ buffer) so window isn't tiny
FOLLOWUP_S = float(os.environ.get("AIPC_WAKE_FOLLOWUP_S", "10"))  # fallback if no TTS dur
FOLLOWUP_MIN_S = float(os.environ.get("AIPC_WAKE_FOLLOWUP_MIN_S", "4"))
FOLLOWUP_MAX_S = float(os.environ.get("AIPC_WAKE_FOLLOWUP_MAX_S", "28"))
FOLLOWUP_SILENCE_S = float(os.environ.get("AIPC_WAKE_FOLLOWUP_SILENCE_S", "2.6"))
FOLLOWUP_GRACE_S = float(os.environ.get("AIPC_WAKE_FOLLOWUP_GRACE_S", "1.0"))
# More frames = less ambient false open (was 4×30ms → noise opens "接话")
FOLLOWUP_ENERGY_FRAMES = int(os.environ.get("AIPC_WAKE_FOLLOWUP_ENERGY_FRAMES", "10"))
FOLLOWUP_POST_TTS_S = float(os.environ.get("AIPC_WAKE_FOLLOWUP_POST_TTS_S", "0.55"))
# Legacy ratio only used as soft hint; thr is ambient-based (see _begin_followup).
FOLLOWUP_ENERGY_RATIO = float(os.environ.get("AIPC_WAKE_FOLLOWUP_ENERGY_RATIO", "1.05"))
# Human speech often 5–10k RMS on this mic; ambient ~3–6k. Cap must stay under
# normal conversation (9000 made 接话 deaf — hardware 2026-07-10).
FOLLOWUP_THR_CAP = float(os.environ.get("AIPC_WAKE_FOLLOWUP_THR_CAP", "6200"))
FOLLOWUP_THR_FLOOR = float(os.environ.get("AIPC_WAKE_FOLLOWUP_THR_FLOOR", "3800"))
# Extra seconds after TTS so user can start speaking (2nd+ min open = tts + this).
# Keep modest — large pad + low thr caused empty 接话 loops (turn79–85).
FOLLOWUP_TTS_PAD_S = float(os.environ.get("AIPC_WAKE_FOLLOWUP_TTS_PAD_S", "2.0"))
# After this many empty/junk captures in a follow-up chain, leave multi-turn
# and hide the overlay (user: 没听到有意义内容就消失).
FOLLOWUP_JUNK_MAX = int(os.environ.get("AIPC_WAKE_FOLLOWUP_JUNK_MAX", "1"))
AUDIO_FRONT = os.environ.get("AIPC_AUDIO_FRONT", "1") not in ("0", "false", "no", "off")
AUDIO_FRONT_URL = os.environ.get(
    "AIPC_AUDIO_FRONT_URL", "http://127.0.0.1:9010/gate"
)
AUDIO_FRONT_TIMEOUT_MS = float(os.environ.get("AIPC_AUDIO_FRONT_TIMEOUT_MS", "400"))
# Barge-in while LLM/TTS is busy: user speech stops reply and starts capture.
BARGE_ENABLE = os.environ.get("AIPC_WAKE_BARGE", "1") not in ("0", "false", "no")
BARGE_ENERGY_RATIO = float(os.environ.get("AIPC_WAKE_BARGE_ENERGY_RATIO", "1.85"))
BARGE_MIN_RMS = float(os.environ.get("AIPC_WAKE_BARGE_MIN_RMS", "20000"))
BARGE_FRAMES = int(os.environ.get("AIPC_WAKE_BARGE_FRAMES", "12"))  # ~360ms
# Reject mic energy that looks like speaker bleed (music/TTS into the mic).
ECHO_GATE = os.environ.get("AIPC_WAKE_ECHO_GATE", "1") not in ("0", "false", "no")
# Mild fixed raise when media plays; prefer adaptive bleed_floor (see voice_audio).
PLAYBACK_ENERGY_RATIO = float(os.environ.get("AIPC_WAKE_PLAYBACK_ENERGY_RATIO", "1.55"))
PLAYBACK_ENERGY_EXTRA = float(os.environ.get("AIPC_WAKE_PLAYBACK_ENERGY_EXTRA", "3500"))
# While TTS is playing, barge needs mic peak clearly above recent bleed peak.
BARGE_OVER_BLEED = float(os.environ.get("AIPC_WAKE_BARGE_OVER_BLEED", "1.35"))
# After TTS ends, ignore follow-up energy this long (speaker ring-down).
# (FOLLOWUP_POST_TTS_S is the main knob; raise default below.)
# Compat aliases
FOLLOWUP1_SILENCE_S = float(os.environ.get("AIPC_WAKE_FOLLOWUP1_SILENCE_S", str(FOLLOWUP_SILENCE_S)))
FOLLOWUP1_GRACE_S = float(os.environ.get("AIPC_WAKE_FOLLOWUP1_GRACE_S", str(FOLLOWUP_GRACE_S)))
WAKE_CTRL_SOCK = Path(os.environ.get("AIPC_WAKE_SOCK", "/run/user/1000/aipc-wake.sock"))
STT_URL = os.environ.get("AIPC_VOICE_STT_URL", "http://127.0.0.1:9001/transcribe")
STT_LANG = os.environ.get("AIPC_WAKE_STT_LANG", "zh")
PHRASES_FILE = Path(
    os.environ.get("AIPC_WAKE_PHRASES_FILE", "/etc/aipc/wake/phrases")
)
# Default custom wake phrases (user-editable via phrases file / env)
DEFAULT_PHRASES = (
    "嘿助理",
    "嘿 助理",
    "你好助理",
    "hey assistant",
    "hi assistant",
)
MODEL_PATH = Path(
    os.environ.get(
        "AIPC_WAKE_MODEL",
        "/var/lib/aipc-voice/wake/user-model.onnx",
    )
)
PRETRAINED = os.environ.get("AIPC_WAKE_PRETRAINED", "hey_jarvis")
OWW_VENV_PYTHON = Path(
    os.environ.get(
        "AIPC_WAKE_OWW_PYTHON",
        "/var/lib/aipc-voice/venv/bin/python",
    )
)



def _capture_env() -> dict:
    """Mic env for wake arecord — basic RNNoise denoise by default.

    Uses virtual source aipc_denoise_out.monitor (noise-suppression-for-voice).
    Disable with AIPC_WAKE_DENOISE=0 if it hurts wake-word STT.
    """
    env = os.environ.copy()
    if os.environ.get("AIPC_WAKE_DENOISE", "1") == "0":
        env.pop("PULSE_SOURCE", None)
        return env
    try:
        from aipc_lib.voice_audio import capture_env, ensure_denoise_source
        ensure_denoise_source()
        return capture_env(env)
    except Exception as exc:
        print(f"aipc-voice-wake: denoise via aipc_lib failed: {exc}", flush=True)
    try:
        import voice_audio  # type: ignore
        voice_audio.ensure_denoise_source()
        return voice_audio.capture_env(env)
    except Exception as exc:
        print(f"aipc-voice-wake: denoise via voice_audio failed: {exc}", flush=True)
    env.setdefault("PULSE_SOURCE", "aipc_denoise_out.monitor")
    return env

def muted() -> bool:
    return MUTE_FLAG.exists() or USER_MUTE_FLAG.exists()


def load_phrases() -> list[str]:
    """Load wake phrases: env AIPC_WAKE_PHRASES, else phrases file, else defaults."""
    env = os.environ.get("AIPC_WAKE_PHRASES", "").strip()
    raw: list[str] = []
    if env:
        raw = [p.strip() for p in env.split(",") if p.strip()]
    elif PHRASES_FILE.is_file():
        for line in PHRASES_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw.append(line)
    else:
        raw = list(DEFAULT_PHRASES)
    # Drop very short tokens (high false positive)
    out = [p for p in raw if len(_norm(p)) >= 2]
    return out or list(DEFAULT_PHRASES)


def _desktop_user_env() -> dict[str, str]:
    """Inject the active graphical session so TTS/notify path works."""
    import pwd

    env = os.environ.copy()
    run_user = Path("/run/user")
    if not run_user.is_dir():
        return env
    for entry in sorted(run_user.iterdir(), key=lambda p: p.name):
        if not entry.name.isdigit():
            continue
        bus = entry / "bus"
        if not bus.exists():
            continue
        uid = int(entry.name)
        try:
            pw = pwd.getpwuid(uid)
        except KeyError:
            continue
        if pw.pw_name in ("root", "nobody"):
            continue
        env["DISPLAY"] = env.get("DISPLAY") or ":0"
        env["XDG_RUNTIME_DIR"] = str(entry)
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
        env["HOME"] = pw.pw_dir
        env["USER"] = pw.pw_name
        env["LOGNAME"] = pw.pw_name
        env["AIPC_WAKE_AS_USER"] = pw.pw_name
        local_once = Path(pw.pw_dir) / ".local/bin/aipc-voice-once"
        if local_once.is_file() and os.access(local_once, os.X_OK):
            env["AIPC_VOICE_ONCE_RESOLVED"] = str(local_once)
        return env
    env.setdefault("DISPLAY", ":0")
    return env


def _write_pcm_wav(path: str, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


class PartialSttWorker:
    """Background STT snapshots while the user is still talking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text = ""
        self._busy = False
        self._gen = 0
        self._pending: bytes | None = None

    def reset(self) -> None:
        with self._lock:
            self._gen += 1
            self._text = ""
            self._pending = None
            self._busy = False

    def get_text(self) -> str:
        with self._lock:
            return self._text

    def request(self, pcm: bytes) -> None:
        if len(pcm) < int(SAMPLE_RATE * PARTIAL_STT_MIN_S) * 2:
            return
        with self._lock:
            if self._busy:
                self._pending = bytes(pcm)
                return
            self._busy = True
            gen = self._gen
            snap = bytes(pcm)

        def _run() -> None:
            nonlocal snap, gen
            while True:
                text = ""
                fd, path = tempfile.mkstemp(suffix=".wav", prefix="aipc-partial-")
                os.close(fd)
                try:
                    _write_pcm_wav(path, snap)
                    text = _stt_wav(path)
                except Exception as exc:  # noqa: BLE001
                    print(f"aipc-voice-wake: partial STT fail: {exc}", flush=True)
                    text = ""
                finally:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                with self._lock:
                    if gen != self._gen:
                        self._busy = False
                        self._pending = None
                        return
                    if text and text.strip():
                        self._text = text.strip()
                        show = self._text
                    else:
                        show = self._text
                    pending = self._pending
                    self._pending = None
                    if pending is None:
                        self._busy = False
                        if show:
                            # Overlay partial while still recording
                            if voice_ux:
                                try:
                                    voice_ux.write_status("recording", "", partial=show[:120])
                                except Exception:
                                    pass
                            print(f"aipc-voice-wake: partial STT: {show[:80]!r}", flush=True)
                        return
                    snap = pending
                    # keep busy, process latest snapshot

        threading.Thread(target=_run, name="aipc-partial-stt", daemon=True).start()


def _kill_process_group(proc: subprocess.Popen, reason: str = "") -> None:
    """Stop once + paplay/ffplay children (once runs in its own session)."""
    tag = f" ({reason})" if reason else ""
    pid = proc.pid
    try:
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        proc.wait(timeout=0.45)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        print(f"aipc-voice-wake: kill once timed out{tag} pid={pid}", flush=True)


class OnceWorker:
    """Background aipc-voice-once runner (no mic). Latest job wins.

    Policy:
    - submit while idle → start immediately
    - submit while busy → cancel current (barge-in) and start new
    - energy/PTT barge while busy → cancel without on_finished side effects
    Mic stays owned by the phrase-loop stream; jobs only get --wav paths.
    """

    def __init__(self, on_finished=None) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._gen = 0
        self._on_finished = on_finished  # callable(ok: bool, rc: int=0) | None

    def busy(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def cancel_speech(self, reason: str = "speech-cancel") -> bool:
        """Stop TTS/orphan playback only — leave the task (voice-once) running.

        Criterion: barge-in stops speech without cancelling the underlying task
        unless the user explicitly cancels the task.
        """
        stopped = False
        try:
            for p in (
                Path("/var/lib/aipc-voice/lib"),
                Path("/usr/lib/aipc-voice"),
            ):
                if (p / "aipc_voice_tts.py").is_file():
                    import sys

                    if str(p) not in sys.path:
                        sys.path.insert(0, str(p))
                    import aipc_voice_tts  # type: ignore

                    if hasattr(aipc_voice_tts, "stop_active_tts"):
                        aipc_voice_tts.stop_active_tts()
                        stopped = True
                    break
        except Exception as exc:  # noqa: BLE001
            print(f"aipc-voice-wake: cancel_speech tts module fail: {exc}", flush=True)
        # Defense: kill only aipc-tts players, not the once worker itself
        try:
            uid = os.getuid()
            for pat in (
                "paplay.*aipc-tts-",
                "ffplay.*aipc-tts-",
                "pw-play.*aipc-tts-",
            ):
                subprocess.run(
                    ["pkill", "-u", str(uid), "-f", pat],
                    check=False,
                    capture_output=True,
                    timeout=2,
                )
                stopped = True
        except Exception:
            pass
        print(f"aipc-voice-wake: cancel speech only ({reason})", flush=True)
        return stopped

    def cancel(self, reason: str = "barge-in") -> bool:
        """Cancel speech or full task depending on reason.

        Speech-only: speech-barge, ptt-barge, speech-cancel, barge-in.
        Full task kill: new-job, shutdown, mic-reconnect, task-cancel, …
        """
        speech_only = reason in (
            "speech-barge",
            "ptt-barge",
            "speech-cancel",
            "barge-in",
        ) or str(reason).startswith("speech")
        if speech_only:
            return self.cancel_speech(reason)
        with self._lock:
            proc = self._proc
            live = proc is not None and proc.poll() is None
            self._proc = None
            self._gen += 1
        if live and proc is not None:
            print(f"aipc-voice-wake: cancel voice-once task ({reason})", flush=True)
            _kill_process_group(proc, reason)
        # Also stop any orphan TTS from a prior agent path
        self.cancel_speech(f"with-task:{reason}")
        return live

    def submit_wav(self, wav_path: str, text: str | None = None) -> None:
        """Run once/stream --wav asynchronously; barge-in cancels prior job.

        If text is provided, worker skips STT (progressive transcript).
        When AIPC_VOICE_STREAM=1 and aipc-voice-stream is present, prefer the
        streaming turn worker; otherwise batch aipc-voice-once (default).
        """
        self.cancel(reason="new-job")
        gen = self._gen

        def _run() -> None:
            env = _desktop_user_env()
            use_stream = env.get("AIPC_VOICE_STREAM", os.environ.get("AIPC_VOICE_STREAM", "0"))
            use_stream = use_stream not in ("0", "false", "no", "")
            stream_cmd = env.get("AIPC_VOICE_STREAM_CMD") or STREAM_CMD
            once_cmd = env.pop("AIPC_VOICE_ONCE_RESOLVED", None) or ONCE_CMD
            cmd = once_cmd
            if use_stream:
                sc = stream_cmd
                if not Path(sc).is_file() and shutil.which(sc):
                    sc = shutil.which(sc) or sc
                if Path(sc).is_file() or shutil.which(sc):
                    cmd = sc
                else:
                    print(
                        "aipc-voice-wake: AIPC_VOICE_STREAM=1 but stream worker missing; batch once",
                        flush=True,
                    )
            if not Path(cmd).is_file() and shutil.which(cmd):
                cmd = shutil.which(cmd) or cmd
            argv = [cmd, "--wav", wav_path]
            if text and text.strip():
                argv.extend(["--text", text.strip()])
            as_user = env.get("AIPC_WAKE_AS_USER")
            # Already running as desktop user in service; no runuser needed.
            if as_user and os.geteuid() == 0 and as_user != "root":
                argv = ["runuser", "-u", as_user, "--", *argv]
            log_name = (
                "voice-stream-from-wake.log"
                if "stream" in Path(cmd).name
                else "voice-once-from-wake.log"
            )
            log_path = Path(env.get("HOME", "/tmp")) / ".cache/aipc" / log_name
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_f = open(log_path, "ab", buffering=0)  # noqa: SIM115
            except OSError:
                log_f = subprocess.DEVNULL
            print(f"aipc-voice-wake: async once {' '.join(argv)}", flush=True)
            try:
                proc = subprocess.Popen(
                    argv, env=env, stdout=log_f, stderr=log_f, start_new_session=True
                )
            except OSError as exc:
                print(f"aipc-voice-wake: once spawn failed: {exc}", flush=True)
                with self._lock:
                    superseded = gen != self._gen
                if not superseded and self._on_finished:
                    try:
                        self._on_finished(False)
                    except Exception:
                        pass
                return
            with self._lock:
                if gen != self._gen:
                    _kill_process_group(proc, "superseded-at-start")
                    return
                self._proc = proc
            rc = proc.wait()
            with self._lock:
                superseded = gen != self._gen
                if self._proc is proc:
                    self._proc = None
            if superseded:
                print(
                    f"aipc-voice-wake: async once cancelled rc={rc} (no follow-up)",
                    flush=True,
                )
            else:
                print(f"aipc-voice-wake: async once finished rc={rc}", flush=True)
                # rc 0 = success/done; rc 2 = success end session; rc 3 =
                # success + assistant expects a reply; rc 4 = success +
                # detached to background. All four are non-error turn
                # outcomes (see aipc-voice-once._turn_rc) — anything else
                # (mic/STT/network failure) is a real failure.
                ok = rc in (0, 2, 3, 4)
                if self._on_finished is not None:
                    try:
                        self._on_finished(ok, rc=rc)
                    except TypeError:
                        try:
                            self._on_finished(ok)
                        except Exception as exc:  # noqa: BLE001
                            print(f"aipc-voice-wake: on_finished failed: {exc}", flush=True)
                    except Exception as exc:  # noqa: BLE001
                        print(f"aipc-voice-wake: on_finished failed: {exc}", flush=True)
                else:
                    if ok:
                        _ux("done", force=True)
                        _ux("listening")
                    else:
                        _ux("error", f"voice-once rc={rc}", force=True)
                        _ux("listening")
            try:
                os.unlink(wav_path)
            except OSError:
                pass
            if log_f is not subprocess.DEVNULL:
                try:
                    log_f.close()
                except Exception:
                    pass

        t = threading.Thread(target=_run, name="aipc-once-worker", daemon=True)
        with self._lock:
            self._thread = t
        t.start()


def trigger_once(*, wait: bool = False, timeout: float = 180.0, wav: str | None = None) -> int:
    """Legacy helper: prefer OnceWorker.submit_wav for non-blocking path."""
    env = _desktop_user_env()
    cmd = env.pop("AIPC_VOICE_ONCE_RESOLVED", None) or ONCE_CMD
    if not Path(cmd).is_file() and shutil.which(cmd):
        cmd = shutil.which(cmd) or cmd
    as_user = env.get("AIPC_WAKE_AS_USER")
    argv = [cmd, "--wav", wav] if wav else [cmd, "--vad"]
    if as_user and os.geteuid() == 0 and as_user != "root":
        argv = ["runuser", "-u", as_user, "--", *argv]
    log = Path(env.get("HOME", "/tmp")) / ".cache/aipc/voice-once-from-wake.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(log, "ab", buffering=0)  # noqa: SIM115
    except OSError:
        log_f = subprocess.DEVNULL
    print(f"aipc-voice-wake: run {' '.join(argv)} wait={wait}", flush=True)
    if wait:
        try:
            r = subprocess.run(argv, env=env, stdout=log_f, stderr=log_f, timeout=timeout)
            return int(r.returncode)
        except subprocess.TimeoutExpired:
            return 124
        finally:
            if log_f is not subprocess.DEVNULL:
                try:
                    log_f.close()
                except Exception:
                    pass
    subprocess.Popen(argv, env=env, stdout=log_f, stderr=log_f, start_new_session=True)
    return 0


def _rms(frame: bytes) -> float:
    if len(frame) < 2:
        return 0.0
    n = len(frame) // 2
    samples = array.array("h")
    samples.frombytes(frame[: n * 2])
    if not samples:
        return 0.0
    acc = 0
    for s in samples:
        acc += s * s
    return (acc / len(samples)) ** 0.5


def _record_wav_seconds(path: str, seconds: float) -> None:
    subprocess.run(
        [
            "arecord",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
            "-d",
            str(max(0.4, int(seconds) if float(seconds).is_integer() else seconds)),
            path,
        ],
        check=True,
        capture_output=True,
    )


def _progressive_core(text: str) -> str:
    """Normalize transcript for stability (ignore emoji/punct flip-flops)."""
    s = (text or "").strip()
    return re.sub(r"[\s\W_😔😊😂😅…·。！？!?，,、；;：:\"'“”‘’]+", "", s, flags=re.UNICODE)


_JUNK_PARTICLES = frozenset(
    {
        "我",
        "嗯",
        "啊",
        "呃",
        "哦",
        "喔",
        "呀",
        "的",
        "了",
        "吗",
        "呢",
        "吧",
        "哈",
        "嘿",
        "唔",
        "恩",
        "那个",
        "就是",
    }
)


def _progressive_usable(text: str) -> bool:
    """True if progressive STT looks like a real utterance (not noise/punct).

    Hardware 2026-07-10: ambient → STT '我。' / '。' was treated as content,
    once returned rc=0, follow-up re-opened forever (turn79+ loop).
    """
    core = _progressive_core(text)
    if len(core) < 2:
        return False
    if core in _JUNK_PARTICLES:
        return False
    cjk = sum(1 for c in core if "一" <= c <= "鿿")
    if cjk >= 2:
        return True
    alnum = sum(1 for c in core if c.isalnum())
    return alnum >= 3


def _progressive_looks_complete(text: str) -> bool:
    """Heuristic: progressive STT likely finished a thought (not mid-phrase).

    Hardware 2026-07-10: end_silence_fast on usable-but-short text cut
    mid-sentence (e.g. short fragments before the rest of the utterance).
    """
    core = _progressive_core(text)
    if len(core) < 5:
        return False
    raw = (text or "").strip()
    if any(raw.endswith(x) for x in ("？", "?", "！", "!", "吗", "呢", "吧", "啊")):
        return len(core) >= 3
    trailers = (
        "的", "了", "是", "在", "和", "跟", "与", "把", "被", "就", "还", "會", "会",
        "要", "想", "能", "可", "对", "對", "给", "給", "从", "從", "到", "比",
        "那", "这", "這", "我", "你", "他", "她", "它", "们", "們",
    )
    for t in trailers:
        if core.endswith(t):
            return False
    # Short cores are incomplete even if STT added a period
    if len(core) < 8:
        return False
    return True


def _stt_wav(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    url = STT_URL
    if "language=" not in url and STT_LANG:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}language={STT_LANG}"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "audio/wav"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read())
    return str(body.get("text") or "").strip()


def stt_available() -> bool:
    try:
        base = STT_URL.rsplit("/", 1)[0]
        req = urllib.request.Request(f"{base}/healthz", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _arecord_raw_cmd() -> list[str]:
    return [
        "arecord",
        "-f",
        "S16_LE",
        "-r",
        str(SAMPLE_RATE),
        "-c",
        "1",
        "-t",
        "raw",
        "-q",
        "-",
    ]


def _open_arecord_raw() -> subprocess.Popen:
    """Open continuous raw capture; raise if PipeWire/ALSA rejects us."""
    proc = subprocess.Popen(
        _arecord_raw_cmd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_capture_env(),
    )
    assert proc.stdout is not None
    time.sleep(0.15)
    if proc.poll() is not None:
        err = (proc.stderr.read() if proc.stderr else b"").decode(errors="replace")
        raise RuntimeError(
            f"arecord failed immediately (rc={proc.returncode}): {err.strip() or 'no stderr'} "
            f"— wake must run as desktop user with XDG_RUNTIME_DIR (not bare root)"
        )
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    chunk = proc.stdout.read(frame_bytes)
    if not chunk:
        raise RuntimeError("arecord opened but produced no audio frames")
    print(f"aipc-voice-wake: mic ok first_frame_rms={_rms(chunk):.0f}", flush=True)
    return proc


def _calibrate_noise(proc: subprocess.Popen, seconds: float = 1.5) -> float:
    """Estimate ambient RMS; return adaptive speech threshold."""
    assert proc.stdout is not None
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    n = max(1, int(seconds * 1000 // FRAME_MS))
    vals: list[float] = []
    for _ in range(n):
        data = proc.stdout.read(frame_bytes)
        if not data:
            break
        vals.append(_rms(data))
    if not vals:
        return ENERGY_THRESHOLD
    vals.sort()
    noise = vals[max(0, len(vals) // 5)]
    # With RNNoise denoise ON the noise floor is low (~2k) but speech is also
    # attenuated toward it — measured hw 2026-07-14: ambient ~2182, spoken
    # 嘿助理 p95 only ~3086. The old 1.35×+600 (=3546) sat ABOVE speech p95, so
    # the gate almost never opened (3/266 frames > thr). Sit just above ambient
    # so attenuated speech still trips it; the 1.5s miss-cooldown absorbs the
    # extra ambient false-opens cleanly. Tunable: AIPC_WAKE_CALIB_RATIO / _OFFSET.
    ratio = float(os.environ.get("AIPC_WAKE_CALIB_RATIO", "1.15"))
    offset = float(os.environ.get("AIPC_WAKE_CALIB_OFFSET", "100.0"))
    adaptive = max(ENERGY_THRESHOLD, noise * ratio + offset)
    adaptive = min(adaptive, max(4000.0, noise + 1800.0), 8000.0)

    print(
        f"aipc-voice-wake: calibrated noise_rms={noise:.0f} "
        f"threshold={adaptive:.0f} (min_env={ENERGY_THRESHOLD})",
        flush=True,
    )
    return adaptive


def _ctrl_sock_path() -> Path:
    # Prefer live user runtime; fall back to /tmp
    uid = os.geteuid()
    candidates = [
        Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")) / "aipc-wake.sock",
        Path(f"/tmp/aipc-wake-{uid}.sock"),
    ]
    if "AIPC_WAKE_SOCK" in os.environ:
        return Path(os.environ["AIPC_WAKE_SOCK"])
    for c in candidates:
        try:
            c.parent.mkdir(parents=True, exist_ok=True)
            return c
        except OSError:
            continue
    return candidates[-1]


def run_phrase_loop() -> int:
    # Best-effort basic denoise chain before opening mic
    try:
        from aipc_lib.voice_audio import ensure_denoise_source
        ensure_denoise_source()
    except Exception:
        try:
            import voice_audio  # type: ignore
            voice_audio.ensure_denoise_source()
        except Exception:
            pass

    """Single-mic async pipeline.

    Stream ownership: one arecord for the whole service.
    States:
      listen  — energy gate + short wake STT
      command — same stream, end-of-speech VAD for the user command
    Jobs (STT/LLM/TTS via aipc-voice-once --wav) run in a background worker.
    Policy:
      - new wake/ptt while recording command → interrupt & restart command capture
      - new job while worker busy → barge-in cancel previous once
      - user speech (or PTT) while once busy → barge-in: kill TTS, start command
    External PTT: write line "ptt" to $XDG_RUNTIME_DIR/aipc-wake.sock
    """
    import select
    import socket

    phrases = load_phrases()
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    wake_frames = max(1, int(CAPTURE_S * 1000 // FRAME_MS))
    preroll_n = max(1, 700 // FRAME_MS)
    end_need = max(1, CMD_END_SILENCE_MS // FRAME_MS)
    end_need_fast = max(1, CMD_END_SILENCE_FAST_MS // FRAME_MS)
    min_speech_frames = max(1, CMD_MIN_SPEECH_MS // FRAME_MS)
    cmd_max_frames = max(1, int(CMD_MAX_S * 1000 // FRAME_MS))
    followup_until = 0.0  # hard deadline (tts mode or vad max cap)
    followup_high = 0
    followup_quiet = 0
    followup_mode: str | None = None  # "vad" | "tts" | None
    followup_started = 0.0
    followup_speech_thr = 0.0
    # Number of successful once turns in the current conversation chain.
    followup_turn = 0
    followup_quiet_need = max(1, int(FOLLOWUP_SILENCE_S * 1000 // FRAME_MS))
    followup_min_open_s = 0.0  # set per turn in _begin_followup
    followup_junk = 0  # consecutive empty/junk captures in this chain
    last_submit_usable = False  # only re-open follow-up after real content
    barge_high = 0  # loud frames while once busy (speech barge-in)
    tts_bleed_peak = 0.0  # max mic RMS while once busy (speaker → mic)
    playback_gate_log_t = 0.0  # rate-limit "playback gate" logs
    bleed_floor = 0.0  # EMA of mic while not clearly speaking (music bleed)
    miss_streak = 0  # consecutive energy-open without wake phrase
    # Explicit session state machine (aipc_voice_session); intentional/reprompt live here.
    session = Session()
    session_intentional = False  # mirrored for nested closures / logs
    reprompt_used = 0

    def _clear_followup(reason: str = "", *, hide: bool = True) -> None:
        """End multi-turn; by default hide overlay (listening → disappear)."""
        nonlocal followup_until, followup_high, followup_quiet, followup_mode
        nonlocal followup_started, followup_turn, followup_speech_thr, followup_min_open_s
        nonlocal followup_junk, last_submit_usable
        nonlocal session_intentional, reprompt_used, session, miss_streak
        was = followup_mode is not None or followup_turn > 0
        followup_until = 0.0
        followup_high = 0
        followup_quiet = 0
        followup_mode = None
        followup_started = 0.0
        followup_speech_thr = 0.0
        followup_min_open_s = 0.0
        followup_turn = 0
        followup_junk = 0
        last_submit_usable = False
        session_intentional = False
        reprompt_used = 0
        # Keep miss_streak for thrash backoff; clear intentional arm state.
        session = Session(
            state=SessionState.IDLE,
            intentional=False,
            reprompt_used=0,
            miss_streak=session.miss_streak,
            followup_turn=0,
        )
        if reason:
            print(f"aipc-voice-wake: follow-up closed ({reason})", flush=True)
        if hide:
            # No "请再说" linger — go straight to idle hide.
            _ux("listening", force=True)

    def _rearm_command_capture(*, seed: list | None = None) -> None:
        """Re-open command mode on the same mic stream (reprompt / PTT)."""
        nonlocal mode, cmd_buf, cmd_frames, cmd_silent, cmd_speech
        nonlocal cmd_speech_run, cmd_speech_frames, cmd_t0
        nonlocal cmd_prog_text, cmd_prog_stable_since, partial_last_req
        mode = "command"
        cmd_buf = bytearray()
        for f in seed or []:
            cmd_buf.extend(f)
        cmd_frames = 0
        cmd_silent = 0
        cmd_speech = False
        cmd_speech_run = 0
        cmd_speech_frames = 0
        cmd_t0 = time.monotonic()
        cmd_prog_text = ""
        cmd_prog_stable_since = 0.0
        partial_stt.reset()
        partial_last_req = 0.0
        _arm_command_vad(list(seed or []))

    def _drop_empty_capture(reason: str) -> None:
        """Empty/junk after command: intentional → REPROMPT once; else idle hide."""
        nonlocal followup_junk, session_intentional, reprompt_used, mode, session
        followup_junk += 1
        session, action = on_empty_capture(session)
        session_intentional = session.intentional
        reprompt_used = session.reprompt_used
        print(
            f"aipc-voice-wake: empty/junk capture → {action} ({reason}) "
            f"junk={followup_junk} intentional={session_intentional} "
            f"reprompt_used={reprompt_used}",
            flush=True,
        )
        partial_stt.reset()
        if action == "reprompt":
            # reprompt_used already advanced by on_empty_capture
            _ux("no_speech", REPROMPT_TEXT, force=True)
            print(
                f"aipc-voice-wake: reprompt {REPROMPT_TEXT!r} "
                f"({reprompt_used}/{MAX_REPROMPTS})",
                flush=True,
            )
            _ux("recording", force=True)
            _rearm_command_capture()
            mode = next_mode_after_empty_capture(action)  # "command"
            return
        # Idle: must leave command mode or start-timeout re-fires every frame.
        mode = next_mode_after_empty_capture(action)  # "listen"
        _clear_followup(reason, hide=True)

    def _audio_front_ignore(wav_path: str) -> bool:
        """True if front gate says ignore. Fail-soft (False) if gate down/slow."""
        if not AUDIO_FRONT:
            return False
        try:
            with open(wav_path, "rb") as f:
                body = f.read()
            req = urllib.request.Request(
                AUDIO_FRONT_URL,
                data=body,
                method="POST",
                headers={"Content-Type": "audio/wav"},
            )
            t0 = time.monotonic()
            with urllib.request.urlopen(
                req, timeout=max(0.05, AUDIO_FRONT_TIMEOUT_MS / 1000.0)
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            ms = (time.monotonic() - t0) * 1000
            action = str(data.get("action") or "")
            conf = data.get("confidence")
            print(
                f"aipc-voice-wake: audio-front action={action} conf={conf} "
                f"ms={ms:.0f} rms={data.get('rms')}",
                flush=True,
            )
            return action == "ignore"
        except Exception as exc:  # noqa: BLE001
            print(f"aipc-voice-wake: audio-front fail-soft: {exc}", flush=True)
            return False

    def _read_last_tts_sec() -> float | None:
        try:
            from aipc_voice_tts import read_last_tts_seconds

            return read_last_tts_seconds()
        except Exception:
            pass
        xdg = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        for p in (
            Path(xdg) / "aipc-last-tts-sec",
            Path("/tmp/aipc-last-tts-sec"),
            Path.home() / ".cache/aipc/last-tts-sec",
        ):
            try:
                v = float(p.read_text(encoding="utf-8").strip())
                return v if v > 0 else None
            except (OSError, ValueError):
                continue
        return None

    def _begin_followup() -> None:
        nonlocal followup_until, followup_high, followup_quiet, followup_mode
        nonlocal followup_started, followup_turn, followup_speech_thr, followup_min_open_s
        if FOLLOWUP_S < 0:
            _ux("done", force=True)
            _ux("listening")
            return
        followup_turn += 1
        followup_high = 0
        followup_quiet = 0
        # Post-TTS cooldown: ignore energy briefly (speaker bleed).
        followup_started = time.monotonic() + FOLLOWUP_POST_TTS_S
        # Root: do NOT derive thr from wake energy_thr. Miss-streak inflates it
        # to 12k → follow-up caps at 9k → normal speech never opens (user:
        # 接话听不到). Mirror command VAD: thr from recent ambient (preroll).
        noise = _percentile_rms(list(preroll), 0.25) if preroll else 0.0
        if noise < 500.0:
            noise = max(float(cmd_noise or 0.0), float(bleed_floor) * 0.85, 2800.0)
        noise = max(800.0, min(noise, 5200.0))
        thr = max(FOLLOWUP_THR_FLOOR, noise * 1.32 + 350.0)
        if bleed_floor > 0:
            thr = max(thr, min(bleed_floor * 1.18 + 500.0, FOLLOWUP_THR_CAP))
        if cmd_speech_thr > 0:
            thr = min(thr, max(cmd_speech_thr * 1.05, FOLLOWUP_THR_FLOOR))
        followup_speech_thr = min(max(thr, FOLLOWUP_THR_FLOOR), FOLLOWUP_THR_CAP)
        tts_sec = _read_last_tts_sec()
        # All multi-turn follow-ups use VAD silence to close (dynamic).
        # Min open: 1st = grace; 2nd+ = max(tts+pad, FOLLOWUP_MIN) capped modestly.
        followup_mode = "vad"
        if followup_turn <= 1:
            followup_min_open_s = FOLLOWUP_GRACE_S
            why = "turn1-vad"
        else:
            tts_v = float(tts_sec) if tts_sec and tts_sec > 0 else FOLLOWUP_S
            # Cap pad so short junk TTS (「没听清」~2s) does not keep 11s windows
            followup_min_open_s = max(
                FOLLOWUP_MIN_S,
                min(FOLLOWUP_MAX_S, min(tts_v, 8.0) + FOLLOWUP_TTS_PAD_S),
            )
            why = f"turn{followup_turn}-vad min=tts+pad ({tts_sec!r}+{FOLLOWUP_TTS_PAD_S})"
        followup_until = followup_started + FOLLOWUP_MAX_S
        direct = "direct" if FOLLOWUP_DIRECT else "energy-gate"
        print(
            f"aipc-voice-wake: follow-up open {direct} {why} "
            f"speech>={followup_speech_thr:.0f} min_open={followup_min_open_s:.1f}s "
            f"silence≥{FOLLOWUP_SILENCE_S:.0f}s post_tts={FOLLOWUP_POST_TTS_S:.1f}s "
            f"cap={FOLLOWUP_MAX_S:.0f}s bleed={bleed_floor:.0f}",
            flush=True,
        )
        if FOLLOWUP_DIRECT:
            _ux(
                "followup",
                f"可接话 · 正在听 · 说完停一下 · 安静{FOLLOWUP_SILENCE_S:.0f}s结束",
                force=True,
            )
        else:
            _ux(
                "followup",
                f"可接话 · 至少{followup_min_open_s:.0f}s · 安静{FOLLOWUP_SILENCE_S:.0f}s结束",
                force=True,
            )

    # Default ON (2026-07-14): the rc==3 (expect_reply) turn-state contract was
    # dead in practice — 0 follow-up opens in 12h of journal, so every reply
    # ended the turn and the user had to re-wake/PTT to continue (回覆後不給再
    # 回覆). _begin_followup() opens a SHORT, silence-closed window (~3s of
    # quiet dismisses it), not the old 60s+30s "always listening" the user
    # rejected before. A real farewell still short-circuits via rc=2 above.
    # Set AIPC_WAKE_FOLLOWUP_ALWAYS=0 to revert to rc==3-only.
    _FOLLOWUP_ALWAYS = os.environ.get("AIPC_WAKE_FOLLOWUP_ALWAYS", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    def _on_once_finished(ok: bool, rc: int = 0) -> None:
        nonlocal followup_turn, last_submit_usable, followup_junk
        nonlocal miss_streak, energy_thr
        # rc=2: agent said conversation is over (再见/没事了…) — hide, no 接话
        if ok and rc == 2:
            last_submit_usable = False
            print("aipc-voice-wake: session-end → dismiss", flush=True)
            _clear_followup("session-end", hide=True)
            _ux("listening", force=True)
            return
        # rc=4: turn auto-detached to a background job (long Hermes run past
        # DETACH_S, or explicit "后台慢慢做"). Mic frees like a done turn (no
        # follow-up window) — same bookkeeping as the no-expect_reply case —
        # but voice-once already painted a persistent "bg_task" pending pill
        # before exiting; do NOT force the overlay back to "listening" here,
        # it must persist until the background completion notify replaces it.
        if ok and rc == 4:
            followup_junk = 0
            last_submit_usable = False
            miss_streak = 0
            energy_thr = max(float(ENERGY_THRESHOLD), min(energy_thr * 0.85, 6500.0))
            print(
                "aipc-voice-wake: background detach → mic free, pill persists",
                flush=True,
            )
            _clear_followup("background-detach", hide=False)
            return
        # rc=3: assistant is asking the user something (expect_reply) — open
        # a short follow-up window. This is the ONLY case (besides the
        # AIPC_WAKE_FOLLOWUP_ALWAYS escape hatch) that re-opens listening;
        # everything else answers and returns to idle (turn-state-contract).
        if ok and last_submit_usable and (rc == 3 or _FOLLOWUP_ALWAYS):
            # Only continue multi-turn after a real utterance (not junk STT).
            followup_junk = 0
            last_submit_usable = False
            miss_streak = 0
            energy_thr = max(float(ENERGY_THRESHOLD), min(energy_thr * 0.85, 6500.0))
            _begin_followup()
        elif ok and last_submit_usable:
            # Answered, not expecting a reply → show answer, no follow-up
            # window (the fix for "讲完话还一直听" — was unconditional before).
            followup_junk = 0
            last_submit_usable = False
            miss_streak = 0
            energy_thr = max(float(ENERGY_THRESHOLD), min(energy_thr * 0.85, 6500.0))
            print("aipc-voice-wake: turn done, no expect_reply → no follow-up", flush=True)
            _clear_followup("turn-done")
            _ux("listening")
        elif ok and not last_submit_usable:
            # once "succeeded" but we never marked usable (legacy path) — close chain
            print("aipc-voice-wake: once ok but no usable submit → no follow-up", flush=True)
            _clear_followup("once-no-usable")
            _ux("listening")
        else:
            _clear_followup("once-failed")
            _ux("error", "voice-once failed", force=True)
            _ux("listening")

    worker = OnceWorker(on_finished=_on_once_finished)
    partial_stt = PartialSttWorker()
    partial_last_req = 0.0

    def _percentile_rms(chunks: list[bytes], p: float) -> float:
        vals = [_rms(c) for c in chunks if c]
        if not vals:
            return 0.0
        vals.sort()
        idx = max(0, min(len(vals) - 1, int(round((len(vals) - 1) * p))))
        return float(vals[idx])

    def _arm_command_vad(
        seed_chunks: list[bytes] | None = None,
        *,
        entry_rms: float | None = None,
    ) -> None:
        """Per-turn VAD. Prefer quiet percentile so preroll speech doesn't inflate noise."""
        nonlocal cmd_noise, cmd_peak, cmd_speech_thr, cmd_end_level_base
        seeds = list(seed_chunks or [])
        if not seeds and preroll:
            seeds = list(preroll)
        # Quiet floor — never above energy_thr (inflated seeds caused 18k speech thr).
        noise = _percentile_rms(seeds, 0.20) if seeds else float(energy_thr) * 0.5
        noise = max(600.0, min(noise, float(energy_thr) * 0.85, 7000.0))
        cmd_noise = noise
        # Prefer noise-relative thr; human speech often 5–8k — hard cap.
        cmd_cap = float(os.environ.get("AIPC_WAKE_CMD_SPEECH_CAP", "7000"))
        cmd_speech_thr = max(noise * 1.3, 2200.0)
        cmd_speech_thr = min(cmd_speech_thr, cmd_cap)
        # Follow-up entry already proved energy at entry_rms — thr must not be higher.
        if entry_rms is not None and entry_rms > 0:
            cmd_speech_thr = min(
                cmd_speech_thr, max(entry_rms * 0.6, noise * 1.15, 2500.0)
            )
        cmd_end_level_base = max(noise * 1.1, 800.0)
        cmd_peak = max(noise, entry_rms or 0.0)
        print(
            f"aipc-voice-wake: cmd VAD noise={cmd_noise:.0f} "
            f"speech>={cmd_speech_thr:.0f} end_base={cmd_end_level_base:.0f} "
            f"entry_rms={entry_rms!r} end_silence={CMD_END_SILENCE_MS}ms "
            f"min_speech={CMD_MIN_SPEECH_MS}ms max={CMD_MAX_S}s",
            flush=True,
        )

    print(
        f"aipc-voice-wake: phrase mode phrases={phrases!r} "
        f"energy>={ENERGY_THRESHOLD} wake_cap={CAPTURE_S}s "
        f"cmd_max={CMD_MAX_S}s end_silence={CMD_END_SILENCE_MS}ms "
        f"followup={FOLLOWUP_S}s cooldown={COOLDOWN_S}s stt={STT_URL} (single-mic async)",
        flush=True,
    )
    if not stt_available():
        print("aipc-voice-wake: STT not healthy yet", flush=True)

    try:
        proc = _open_arecord_raw()
    except RuntimeError as exc:
        print(f"aipc-voice-wake: {exc}", flush=True)
        return 2
    assert proc.stdout is not None
    energy_thr = _calibrate_noise(proc, seconds=1.5)

    # Control socket for button / external PTT (non-blocking accept)
    sock_path = _ctrl_sock_path()
    try:
        if sock_path.exists():
            sock_path.unlink()
    except OSError:
        pass
    ctrl: socket.socket | None = None
    try:
        ctrl = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        ctrl.bind(str(sock_path))
        ctrl.listen(4)
        ctrl.setblocking(False)
        try:
            os.chmod(sock_path, 0o666)
        except OSError:
            pass
        print(f"aipc-voice-wake: ctrl socket {sock_path} (send 'ptt')", flush=True)
    except OSError as exc:
        print(f"aipc-voice-wake: ctrl socket unavailable: {exc}", flush=True)
        ctrl = None
    _ux("listening", force=True)

    last_wake_check = time.monotonic()
    high = 0
    empty_reads = 0
    preroll: list[bytes] = []
    # mode: listen | wake_buf | command
    mode = "listen"
    wake_buf = bytearray()
    wake_left = 0
    cmd_buf = bytearray()
    cmd_frames = 0
    cmd_silent = 0
    cmd_speech = False
    cmd_speech_run = 0
    cmd_speech_frames = 0
    cmd_t0 = 0.0
    cmd_noise = 0.0
    cmd_peak = 0.0
    cmd_speech_thr = 0.0
    cmd_end_level_base = 0.0
    cmd_prog_text = ""
    cmd_prog_stable_since = 0.0
    ptt_requested = False

    def _poll_ctrl() -> None:
        nonlocal ptt_requested, mode, cmd_buf, cmd_frames, cmd_silent, cmd_speech
        nonlocal cmd_speech_run, cmd_speech_frames, cmd_t0
        nonlocal followup_until, followup_turn, followup_mode, followup_high, followup_quiet
        nonlocal partial_last_req, cmd_prog_text, cmd_prog_stable_since
        nonlocal energy_thr, miss_streak, session_intentional, reprompt_used, session
        if ctrl is None:
            return
        try:
            r, _, _ = select.select([ctrl], [], [], 0)
        except (OSError, ValueError):
            return
        if not r:
            return
        try:
            conn, _ = ctrl.accept()
        except BlockingIOError:
            return
        try:
            conn.settimeout(0.2)
            data = conn.recv(64).decode(errors="replace").strip().lower()
            conn.close()
        except OSError:
            return
        if data in ("ptt", "command", "1", "push"):
            # Mid-session side button = continue same conversation (same agent
            # session_id + keep followup_turn). Only idle PTT starts a new chain.
            in_session = (
                followup_turn > 0
                or followup_mode is not None
                or last_submit_usable
                or mode == "command"
                or worker.busy()
            )
            print(
                "aipc-voice-wake: ctrl ptt → "
                + ("continue session" if in_session else "new command")
                + " (interrupt if needed)",
                flush=True,
            )
            if worker.busy():
                worker.cancel("ptt-barge")
            _ux("wake", "控制中心 · 接续" if in_session else "控制中心", force=True)
            _ux("recording", force=True)
            ptt_requested = True
            session = on_ptt(session)
            session_intentional = session.intentional
            reprompt_used = session.reprompt_used
            if not in_session:
                # Idle: open a fresh conversation chain
                followup_until = 0.0
                followup_turn = 0
                followup_mode = None
                followup_high = 0
                followup_quiet = 0
            else:
                # Keep followup_turn / last_submit_usable so after this turn
                # multi-turn 接话 continues; only stop the wait timer.
                followup_until = 0.0
                followup_mode = None
                followup_high = 0
                followup_quiet = 0
            # PTT: decay miss-streak thr so command start isn't deaf.
            energy_thr = max(
                float(ENERGY_THRESHOLD),
                min(energy_thr * 0.7, 5500.0),
            )
            miss_streak = 0
            seed = list(preroll)
            _rearm_command_capture(seed=seed)

    def _finish_command(pcm: bytes, reason: str) -> None:
        nonlocal partial_last_req, last_submit_usable, followup_junk
        nonlocal followup_mode, followup_high, followup_quiet
        nonlocal followup_started, followup_min_open_s, followup_until
        if len(pcm) < SAMPLE_RATE // 2:  # <0.25s
            print(f"aipc-voice-wake: command too short reason={reason}", flush=True)
            partial_stt.reset()
            return
        progressive = partial_stt.get_text()
        # Reject ambient→STT junk: dismiss multi-turn, hide overlay (no re-arm).
        if progressive and not _progressive_usable(progressive):
            _drop_empty_capture(f"junk:{progressive[:24]!r}")
            return

        fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="aipc-cmd-")
        os.close(fd)
        _write_pcm_wav(wav_path, bytes(pcm))
        # Front gate on waveform. ignore only when we have no usable STT —
        # progressive text is stronger evidence than RMS (hardware 2026-07-11:
        # 「帮我找最近的头条新闻」rms~3856 → conf=0.45 ignore → UI disappeared).
        if _audio_front_ignore(wav_path):
            if progressive and _progressive_usable(progressive):
                print(
                    "aipc-voice-wake: audio-front ignore overridden by "
                    f"progressive={progressive[:40]!r}",
                    flush=True,
                )
            else:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
                partial_stt.reset()
                _drop_empty_capture("audio-front-ignore")
                return
        print(
            f"aipc-voice-wake: command captured {len(pcm)/2/SAMPLE_RATE:.2f}s "
            f"reason={reason} progressive={progressive[:40]!r} → async once",
            flush=True,
        )
        if reason == "end_silence" or reason == "max":
            detail = progressive[:50] if progressive else f"{len(pcm)/2/SAMPLE_RATE:.1f}s"
            _ux("thinking", detail, force=True)
        if progressive and _progressive_usable(progressive):
            last_submit_usable = True
            followup_junk = 0
            worker.submit_wav(wav_path, text=progressive)
        else:
            # No usable progressive — if peak is weak, treat as silence and dismiss.
            if cmd_peak < (cmd_speech_thr or energy_thr) * 1.2:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
                partial_stt.reset()
                _drop_empty_capture(
                    f"weak-peak peak={cmd_peak:.0f} thr={cmd_speech_thr:.0f}"
                )
                return
            last_submit_usable = True
            worker.submit_wav(wav_path)
        partial_stt.reset()
        partial_last_req = 0.0

    try:
        while True:
            _poll_ctrl()

            if muted():
                _ux("muted")
                time.sleep(0.2)
                proc.stdout.read(frame_bytes)
                high = 0
                _clear_followup("muted")
                mode = "listen"
                continue

            data = proc.stdout.read(frame_bytes)
            if not data:
                empty_reads += 1
                if proc.poll() is not None or empty_reads > 50:
                    err = b""
                    if proc.stderr:
                        try:
                            err = proc.stderr.read() or b""
                        except Exception:
                            pass
                    print(
                        f"aipc-voice-wake: arecord died rc={proc.poll()} "
                        f"{err.decode(errors='replace')[:200]} — reconnect "
                        f"(suspend/resume or PipeWire restart)",
                        flush=True,
                    )
                    # Survive suspend/resume: reopen mic instead of exiting.
                    worker.cancel(reason="mic-reconnect")
                    mode = "listen"
                    high = 0
                    _clear_followup("mic-reconnect")
                    try:
                        if proc.poll() is None:
                            proc.terminate()
                            proc.wait(timeout=2)
                    except Exception:
                        pass
                    reopened = False
                    for attempt in range(1, 16):
                        try:
                            try:
                                from aipc_lib.voice_audio import ensure_denoise_source

                                ensure_denoise_source()
                            except Exception:
                                try:
                                    import voice_audio  # type: ignore

                                    voice_audio.ensure_denoise_source()
                                except Exception:
                                    pass
                            proc = _open_arecord_raw()
                            assert proc.stdout is not None
                            energy_thr = _calibrate_noise(proc, seconds=0.8)
                            empty_reads = 0
                            reopened = True
                            print(
                                f"aipc-voice-wake: mic reconnected attempt={attempt} "
                                f"thr={energy_thr:.0f}",
                                flush=True,
                            )
                            _ux("listening", force=True)
                            break
                        except Exception as exc:
                            print(
                                f"aipc-voice-wake: mic reconnect {attempt}/15 fail: {exc}",
                                flush=True,
                            )
                            time.sleep(min(2.0, 0.4 * attempt))
                    if not reopened:
                        print("aipc-voice-wake: mic reconnect gave up", flush=True)
                        return 2
                    continue
                time.sleep(0.05)
                continue
            empty_reads = 0
            rms = _rms(data)
            # Speaker bleed: media/TTS → speakers → mic looks like speech energy.
            # Track bleed floor so thr can sit just above music (no need to mute).
            pb = _playback_active(include_tts=worker.busy())
            # Never train bleed_floor on command-wait / user speech — that races thr upward
            # (user talks → bleed rises → speech_thr outruns voice → "deaf" start timeout).
            train_bleed = mode not in ("command", "wake_buf")
            if train_bleed:
                try:
                    from aipc_lib.voice_audio import update_bleed_floor as _ubf

                    bleed_floor = float(_ubf(bleed_floor, rms))
                except Exception:
                    try:
                        import voice_audio as _va  # type: ignore

                        bleed_floor = float(_va.update_bleed_floor(bleed_floor, rms))
                    except Exception:
                        if bleed_floor <= 0:
                            bleed_floor = rms
                        elif rms < bleed_floor:
                            bleed_floor = 0.88 * bleed_floor + 0.12 * rms
                        else:
                            bleed_floor = 0.96 * bleed_floor + 0.04 * rms
            gate_thr = _effective_energy_thr(
                energy_thr, playback=pb, bleed_floor=bleed_floor if pb else 0.0
            )
            loud = rms >= gate_thr

            if mode != "wake_buf" and mode != "command":
                preroll.append(data)
                if len(preroll) > preroll_n:
                    preroll.pop(0)

            # ---- command capture (same stream, never open second mic) ----
            if mode == "command":
                cmd_buf.extend(data)
                cmd_frames += 1
                if rms > cmd_peak:
                    cmd_peak = rms
                # Media still on: mild thr bump only. Never fold in energy_thr —
                # miss-streak inflates it to 12k and causes start-timeout deafness
                # (speech_thr=12600 last_rms=5835, 2026-07-11).
                if pb and bleed_floor > 0 and not cmd_speech:
                    try:
                        cmd_cap = float(os.environ.get("AIPC_WAKE_CMD_SPEECH_CAP", "7000"))
                    except ValueError:
                        cmd_cap = 7000.0
                    bumped = max(
                        cmd_speech_thr,
                        min(bleed_floor * 1.08 + 800.0, cmd_cap),
                    )
                    cmd_speech_thr = min(bumped, cmd_cap)

                # Progressive STT: while speaking, snapshot every PARTIAL_STT_S
                if cmd_speech and PARTIAL_STT_S > 0:
                    now_p = time.monotonic()
                    if (now_p - partial_last_req) >= PARTIAL_STT_S:
                        partial_last_req = now_p
                        partial_stt.request(bytes(cmd_buf))
                # Track progressive text stability (normalize emoji/punct so thrashing doesn't reset)
                prog = partial_stt.get_text()
                if _progressive_core(prog) != _progressive_core(cmd_prog_text):
                    cmd_prog_text = prog
                    cmd_prog_stable_since = time.monotonic() if _progressive_usable(prog) else 0.0
                elif not cmd_prog_text and prog:
                    cmd_prog_text = prog
                    cmd_prog_stable_since = time.monotonic() if _progressive_usable(prog) else 0.0
                prog_ok = _progressive_usable(cmd_prog_text)
                prog_done = prog_ok and _progressive_looks_complete(cmd_prog_text)
                # Fast end ONLY when progressive looks complete. Incomplete
                # usable text (「那现在。」) used to take 400ms fast path → cut.
                if prog_done and cmd_peak > cmd_speech_thr:
                    end_level = max(
                        cmd_noise * 1.25,
                        cmd_peak * 0.48,
                        cmd_end_level_base * 0.95,
                    )
                    need_silent = end_need_fast
                    need_speech = max(min_speech_frames, int(0.9 * 1000 // FRAME_MS))
                else:
                    # Mid-utterance / no text: wait longer; quieter speech still "loud"
                    end_level = max(
                        cmd_end_level_base,
                        cmd_noise + 0.40 * max(0.0, cmd_peak - cmd_noise),
                        cmd_peak * 0.45 if cmd_peak > cmd_speech_thr else cmd_end_level_base,
                    )
                    need_silent = end_need
                    # Incomplete progressive: require more speech audio before EOS
                    if prog_ok and not prog_done:
                        need_silent = max(need_silent, int(1300 // FRAME_MS))
                        need_speech = max(min_speech_frames, int(1.8 * 1000 // FRAME_MS))
                    else:
                        need_speech = min_speech_frames
                # Music still playing: "quiet" means back near bleed floor, not absolute silence
                if pb and bleed_floor > 0:
                    end_level = max(end_level, bleed_floor * 1.12)
                if not cmd_speech:
                    if rms >= cmd_speech_thr:
                        cmd_speech_run += 1
                        if cmd_speech_run >= 4:  # ~120ms clear speech
                            cmd_speech = True
                            cmd_silent = 0
                            cmd_speech_frames = 0
                            partial_last_req = 0.0  # allow first partial soon
                    else:
                        cmd_speech_run = 0
                else:
                    cmd_speech_frames += 1
                    # Noise-as-speech: peak never clearly above thr → abort
                    if (
                        cmd_speech_frames >= min_speech_frames
                        and cmd_peak < cmd_speech_thr * 1.12
                    ):
                        mode = "listen"
                        print(
                            f"aipc-voice-wake: command abort noise "
                            f"(peak={cmd_peak:.0f} thr={cmd_speech_thr:.0f})",
                            flush=True,
                        )
                        partial_stt.reset()
                        # No meaningful speech → end 接话 and hide
                        if followup_turn > 0 or last_submit_usable:
                            _clear_followup("command-noise", hide=True)
                        else:
                            _ux("listening", force=True)
                        high = 0
                        continue
                    # Still-loud = user still talking. Cap noise floor contribution:
                    # thr*0.62 + noise*1.25 made ambient ~5.8k look "still speaking"
                    # after thr~9k (hw 2026-07-11: held 18s max after 「现在几点？」).
                    if prog_done:
                        # Finished thought: only loud relative to *this turn's peak*.
                        still_loud = rms >= max(
                            cmd_peak * 0.38,
                            end_level * 0.88,
                            cmd_noise * 1.12,
                        )
                    else:
                        still_loud = rms >= max(
                            cmd_speech_thr * 0.48,
                            end_level * 0.90,
                            cmd_noise * 1.12,
                        )
                    spoken_s = cmd_speech_frames * FRAME_MS / 1000.0
                    # Quiet relative to peak (not only absolute end_level).
                    quiet_cut = max(
                        end_level,
                        cmd_noise * 1.05,
                        cmd_peak * 0.32 if cmd_peak > cmd_speech_thr else end_level,
                    )
                    if prog_done:
                        # Complete STT: allow quieter floor so real silence counts.
                        quiet_cut = min(
                            quiet_cut,
                            max(cmd_noise * 1.08, cmd_peak * 0.28, 1200.0),
                        )
                    if rms < quiet_cut:
                        cmd_silent += 1
                    else:
                        cmd_silent = 0
                    # Complete progressive: end after short stable quiet (not full end_need).
                    stable_need = CMD_TEXT_STABLE_S
                    silent_need_stable = end_need
                    min_speech_stable = CMD_TEXT_STABLE_MIN_SPEECH_S
                    if prog_done:
                        stable_need = min(stable_need, 0.9)
                        silent_need_stable = min(end_need, max(end_need_fast, int(550 // FRAME_MS)))
                        min_speech_stable = min(min_speech_stable, 0.9)
                    if (
                        prog_ok
                        and not still_loud
                        and cmd_prog_stable_since > 0
                        and (time.monotonic() - cmd_prog_stable_since) >= stable_need
                        and spoken_s >= min_speech_stable
                        and cmd_silent >= silent_need_stable
                    ):
                        mode = "listen"
                        print(
                            f"aipc-voice-wake: EOS text-stable+quiet "
                            f"(stable={stable_need:.2f}s silent={cmd_silent * FRAME_MS}ms "
                            f"prog_done={prog_done}) "
                            f"{cmd_prog_text[:40]!r}",
                            flush=True,
                        )
                        _finish_command(bytes(cmd_buf), "text_stable")
                        last_wake_check = time.monotonic()
                        high = 0
                        continue
                    # When STT already complete, use fast end_silence path.
                    if prog_done:
                        need_silent = min(need_silent, max(end_need_fast, int(550 // FRAME_MS)))
                    if (
                        cmd_silent >= need_silent
                        and cmd_speech_frames >= need_speech
                        and not still_loud
                    ):
                        # Incomplete progressive: never end on a brief dip
                        if prog_ok and not prog_done and spoken_s < 3.0:
                            pass
                        else:
                            mode = "listen"
                            _finish_command(bytes(cmd_buf), "end_silence")
                            last_wake_check = time.monotonic()
                            high = 0
                            continue
                if not cmd_speech and (time.monotonic() - cmd_t0) >= CMD_START_TIMEOUT_S:
                    print(
                        f"aipc-voice-wake: command start timeout "
                        f"(speech_thr={cmd_speech_thr:.0f} last_rms={rms:.0f})",
                        flush=True,
                    )
                    # Intentional arm → REPROMPT; follow-up empty → idle hide
                    _drop_empty_capture("start-timeout")
                    high = 0
                    continue
                if cmd_frames >= cmd_max_frames:
                    # If max without a real peak, don't send garbage to STT/LLM
                    if cmd_peak < cmd_speech_thr * 1.12:
                        print(
                            f"aipc-voice-wake: command max discarded as noise "
                            f"(peak={cmd_peak:.0f})",
                            flush=True,
                        )
                        _drop_empty_capture(f"max-noise peak={cmd_peak:.0f}")
                    else:
                        mode = "listen"
                        _finish_command(bytes(cmd_buf), "max")
                    last_wake_check = time.monotonic()
                    high = 0
                continue

            # ---- wake phrase short buffer ----
            if mode == "wake_buf":
                wake_buf.extend(data)
                wake_left -= 1
                if wake_left > 0:
                    continue
                mode = "listen"
                fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="aipc-wake-")
                os.close(fd)
                try:
                    _write_pcm_wav(wav_path, bytes(wake_buf))
                    print(
                        f"aipc-voice-wake: energy → STT check "
                        f"({len(wake_buf)/2/SAMPLE_RATE:.2f}s)",
                        flush=True,
                    )
                    try:
                        text = _stt_wav(wav_path)
                    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                        print(f"aipc-voice-wake: STT check failed: {exc}", flush=True)
                        text = ""
                    tier, hit = (
                        classify_wake_text(text, phrases)
                        if text
                        else ("none", None)
                    )
                    noise_floor = max(500.0, float(energy_thr) * 0.65)
                    wake_score = score_wake_pcm(
                        bytes(wake_buf),
                        noise_floor=noise_floor,
                        thr=float(energy_thr),
                    )
                    decision = decide_wake_arm(
                        tier,
                        wake_score,
                        phrase=hit,
                        ptt=False,
                        allow_fuzzy_promote=ALLOW_FUZZY_PROMOTE,
                        promote_score=PROMOTE_SCORE,
                        candidate_score=CANDIDATE_SCORE,
                    )
                    print(
                        f"aipc-voice-wake: heard {text!r} tier={tier!r} "
                        f"score={wake_score} decision={decision['arm_reason']!r} "
                        f"phrase={hit!r}",
                        flush=True,
                    )
                    if not decision["arm"]:
                        # Prefer miss over ghost: never open wake/recording UX.
                        session = on_wake_decision(session, decision)
                        miss_streak = session.miss_streak
                        _miss_in_playback = _playback_active(include_tts=False)
                        # Escalating cool-off (pure miss_backoff_seconds) —
                        # was ~1.5s → ambient STT thrash + desktop freeze.
                        _backoff = miss_backoff_seconds(miss_streak)
                        last_wake_check = time.monotonic() + _backoff - COOLDOWN_S
                        # Thr-raise only on true none-misses (not fuzzy suppress).
                        if (
                            miss_streak >= 3
                            and decision["arm_reason"] == "none"
                            and not _miss_in_playback
                        ):
                            energy_thr = min(
                                max(energy_thr * 1.05, energy_thr + 100), 6500
                            )
                        print(
                            f"aipc-voice-wake: miss streak={miss_streak} "
                            f"reason={decision['arm_reason']} "
                            f"thr→{energy_thr:.0f} backoff={_backoff:.0f}s"
                            f"{' (playback)' if _miss_in_playback else ''}",
                            flush=True,
                        )
                        if voice_ux and decision["arm_reason"] == "none" and text:
                            try:
                                voice_ux.write_status("miss", text[:40])
                            except Exception:
                                pass
                    else:
                        miss_streak = 0
                        session = on_wake_decision(session, decision)
                        session_intentional = session.intentional
                        reprompt_used = session.reprompt_used
                        energy_thr = max(
                            float(ENERGY_THRESHOLD),
                            min(energy_thr * 0.75, 6500.0),
                        )
                        label = hit or decision["arm_reason"]
                        print(
                            f"aipc-voice-wake: arm {label!r} "
                            f"reason={decision['arm_reason']} "
                            f"→ command (thr={energy_thr:.0f})",
                            flush=True,
                        )
                        _ux("wake", str(label), force=True)
                        _ux("recording", force=True)
                        followup_until = 0.0
                        followup_turn = 0
                        followup_mode = None
                        followup_high = 0
                        followup_quiet = 0
                        tail_chunks = [
                            wake_buf[i : i + frame_bytes]
                            for i in range(0, len(wake_buf), frame_bytes)
                            if len(wake_buf[i : i + frame_bytes]) == frame_bytes
                        ][-12:]
                        _rearm_command_capture(seed=tail_chunks or list(preroll))
                        last_wake_check = time.monotonic()
                finally:
                    try:
                        os.unlink(wav_path)
                    except OSError:
                        pass
                wake_buf.clear()
                high = 0
                continue

            # ---- listen: energy gate ----
            if ptt_requested:
                # Already switched to command in _poll_ctrl. Do NOT call
                # _clear_followup here — it wiped last_submit_usable after a
                # just-finished PTT turn (log: closed(ptt) then no usable).
                ptt_requested = False
                continue

            # Follow-up: open command capture without re-wake.
            # Default DIRECT: after short post-TTS, immediately arm command
            # (resident listen) — no energy-gate wait for speech start.
            if followup_mode and mode == "listen":
                now_fu = time.monotonic()
                # Still in post-TTS cooldown: keep preroll, do not arm yet.
                if now_fu < followup_started:
                    followup_high = 0
                    continue

                def _arm_followup_command(reason: str, entry: float | None = None) -> None:
                    nonlocal followup_mode, followup_until, followup_high, followup_quiet
                    nonlocal mode, cmd_buf, cmd_frames, cmd_silent, cmd_speech
                    nonlocal cmd_speech_run, cmd_speech_frames, cmd_t0
                    nonlocal cmd_prog_text, cmd_prog_stable_since, partial_last_req, high
                    nonlocal session_intentional, reprompt_used, session
                    print(
                        f"aipc-voice-wake: follow-up → command ({reason})",
                        flush=True,
                    )
                    # Follow-up junk: idle hide (no 沒聽清 spam)
                    session = on_followup_speech(session)
                    session_intentional = session.intentional
                    reprompt_used = session.reprompt_used
                    followup_mode = None
                    followup_until = 0.0
                    followup_high = 0
                    followup_quiet = 0
                    high = 0
                    mode = "command"
                    cmd_buf = bytearray()
                    seed = list(preroll)
                    for f in seed:
                        cmd_buf.extend(f)
                    cmd_frames = 0
                    cmd_silent = 0
                    cmd_speech = False
                    cmd_speech_run = 0
                    cmd_speech_frames = 0
                    cmd_t0 = time.monotonic()
                    cmd_prog_text = ""
                    cmd_prog_stable_since = 0.0
                    partial_stt.reset()
                    partial_last_req = 0.0
                    _arm_command_vad(seed, entry_rms=entry)
                    _ux("recording", "接话中…", force=True)

                if FOLLOWUP_DIRECT:
                    _arm_followup_command(
                        f"direct post_tts={FOLLOWUP_POST_TTS_S:.2f}s",
                        entry=rms if rms > 0 else None,
                    )
                    continue

                # Legacy energy-gate path (AIPC_WAKE_FOLLOWUP_DIRECT=0)
                thr = followup_speech_thr or max(
                    FOLLOWUP_THR_FLOOR,
                    min(float(cmd_noise or 2800.0) * 1.32 + 350.0, FOLLOWUP_THR_CAP),
                )
                thr = max(FOLLOWUP_THR_FLOOR, min(thr, FOLLOWUP_THR_CAP))
                if bleed_floor > 0:
                    thr = max(thr, min(bleed_floor * 1.15 + 400.0, FOLLOWUP_THR_CAP))
                if _playback_active(include_tts=False) and bleed_floor > 0:
                    thr = min(
                        max(thr, bleed_floor * 1.2 + 600.0),
                        FOLLOWUP_THR_CAP,
                    )
                fu_loud = rms >= thr
                if fu_loud:
                    followup_high += 1
                    followup_quiet = 0
                else:
                    followup_high = 0
                    followup_quiet += 1

                if followup_high >= FOLLOWUP_ENERGY_FRAMES:
                    _arm_followup_command(
                        f"energy rms={rms:.0f} thr={thr:.0f}",
                        entry=rms,
                    )
                    continue

                # Expire: need min_open (tts-based on 2nd+) then sustained silence
                elapsed = now_fu - followup_started if followup_started else 0.0
                min_open = max(FOLLOWUP_GRACE_S, followup_min_open_s)
                if elapsed >= FOLLOWUP_MAX_S:
                    # Window expired with no meaningful turn → disappear
                    _clear_followup("vad-max", hide=True)
                elif elapsed >= min_open and followup_quiet >= followup_quiet_need:
                    # Sustained quiet — no speech entered → disappear
                    _clear_followup(
                        f"vad-silence {FOLLOWUP_SILENCE_S:.0f}s after {elapsed:.1f}s",
                        hide=True,
                    )
                continue  # don't also fire wake STT during follow-up window

            # While TTS/LLM (voice-once) is running: allow barge-in, not wake STT.
            # Track mic peak as "bleed floor" — barge only if clearly louder.
            if worker.busy() and mode == "listen":
                high = 0
                tts_bleed_peak = max(tts_bleed_peak, rms)
                if not BARGE_ENABLE:
                    barge_high = 0
                    continue
                try:
                    from aipc_lib.voice_audio import barge_energy_thr as _bet

                    barge_thr = float(
                        _bet(
                            energy_thr,
                            bleed_peak=tts_bleed_peak,
                            ratio=BARGE_ENERGY_RATIO,
                            min_rms=BARGE_MIN_RMS,
                            over_bleed=BARGE_OVER_BLEED,
                        )
                    )
                except Exception:
                    barge_thr = max(
                        float(energy_thr) * BARGE_ENERGY_RATIO,
                        BARGE_MIN_RMS,
                        float(energy_thr) + 6000.0,
                        tts_bleed_peak * BARGE_OVER_BLEED,
                    )
                if rms >= barge_thr:
                    barge_high += 1
                else:
                    barge_high = 0
                if barge_high >= BARGE_FRAMES:
                    print(
                        f"aipc-voice-wake: BARGE-IN speech → stop TTS + command "
                        f"(rms={rms:.0f} thr={barge_thr:.0f} bleed_peak={tts_bleed_peak:.0f} "
                        f"frames={BARGE_FRAMES})",
                        flush=True,
                    )
                    worker.cancel("speech-barge")
                    barge_high = 0
                    tts_bleed_peak = 0.0
                    # Keep multi-turn chain; only clear follow-up window state.
                    followup_mode = None
                    followup_until = 0.0
                    followup_high = 0
                    followup_quiet = 0
                    mode = "command"
                    cmd_buf = bytearray()
                    seed = list(preroll)
                    for f in seed:
                        cmd_buf.extend(f)
                    cmd_frames = 0
                    cmd_silent = 0
                    cmd_speech = False
                    cmd_speech_run = 0
                    cmd_speech_frames = 0
                    cmd_t0 = time.monotonic()
                    cmd_prog_text = ""
                    cmd_prog_stable_since = 0.0
                    partial_stt.reset()
                    partial_last_req = 0.0
                    _arm_command_vad(seed, entry_rms=rms)
                    _ux("recording", "插斷 — 請繼續說…", force=True)
                continue
            else:
                # Reset bleed tracker when not in TTS
                if not worker.busy():
                    tts_bleed_peak = 0.0

            if loud:
                high += 1
            else:
                high = 0
            now = time.monotonic()
            if high < ENERGY_FRAMES or (now - last_wake_check) < COOLDOWN_S:
                continue

            # Final playback re-check: while media plays the mic is full of music
            # (logs: 12-18k RMS → STT hears only 「。」). The old 1.05× bar still
            # fired STT on loud music, burning cycles and feeding the miss spiral
            # that deafened wake. Only attempt wake STT on energy clearly above
            # the gate — likely voice-over-music; sustained music is skipped.
            _pb_gate_ratio = float(
                os.environ.get("AIPC_WAKE_PLAYBACK_GATE_RATIO", "1.4")
            )
            if (
                ECHO_GATE
                and _playback_active(include_tts=False)
                and rms < gate_thr * _pb_gate_ratio
            ):
                high = 0
                if now - playback_gate_log_t > 8.0:
                    playback_gate_log_t = now
                    print(
                        f"aipc-voice-wake: playback gate (skip wake STT) "
                        f"rms={rms:.0f} thr={gate_thr:.0f} ratio={_pb_gate_ratio:.2f}",
                        flush=True,
                    )
                continue

            high = 0
            last_wake_check = now
            mode = "wake_buf"
            wake_buf = bytearray()
            for f in preroll:
                wake_buf.extend(f)
            preroll.clear()
            wake_left = wake_frames
            print(
                f"aipc-voice-wake: energy gate open → wake buffering "
                f"(rms={rms:.0f} thr={gate_thr:.0f} playback={pb})",
                flush=True,
            )
            # ambient energy: do not flash overlay (spam); status file only
            if voice_ux:
                try:
                    voice_ux.write_status("detecting", "辨識中")
                except Exception:
                    pass
    except KeyboardInterrupt:
        return 0
    finally:
        worker.cancel(reason="shutdown")
        if ctrl is not None:
            try:
                ctrl.close()
            except OSError:
                pass
            try:
                sock_path.unlink(missing_ok=True)
            except OSError:
                pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


def run_energy_loop() -> int:
    """Energy VAD only — higher false positives; last-resort fallback."""
    frame_bytes = SAMPLE_RATE * FRAME_MS // 1000 * 2
    print(
        f"aipc-voice-wake: energy mode threshold={ENERGY_THRESHOLD} "
        f"cooldown={COOLDOWN_S}s (no phrase/STT gate)",
        flush=True,
    )
    proc = subprocess.Popen(
        [
            "arecord",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
            "-t",
            "raw",
            "-q",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_capture_env(),
    )
    assert proc.stdout is not None
    last = 0.0
    high = 0
    try:
        while True:
            if muted():
                time.sleep(0.2)
                proc.stdout.read(frame_bytes)
                continue
            data = proc.stdout.read(frame_bytes)
            if not data:
                time.sleep(0.05)
                continue
            if _rms(data) >= ENERGY_THRESHOLD:
                high += 1
            else:
                high = 0
            now = time.monotonic()
            if high >= ENERGY_FRAMES and (now - last) >= COOLDOWN_S:
                last = now
                high = 0
                print("aipc-voice-wake: energy trigger → aipc-voice-once", flush=True)
                trigger_once()
    except KeyboardInterrupt:
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def run_openwakeword() -> int:
    """Pretrained openWakeWord (hey_jarvis etc.). Prefer venv with onnx models."""
    # Prefer dedicated venv (system python may lack oww / tflite).
    if OWW_VENV_PYTHON.is_file() and Path(sys.executable).resolve() != OWW_VENV_PYTHON.resolve():
        # Re-exec under venv so import openwakeword works
        argv = [str(OWW_VENV_PYTHON), str(Path(__file__).resolve()), "--mode", "openwakeword"]
        print(f"aipc-voice-wake: re-exec openwakeword via {OWW_VENV_PYTHON}", flush=True)
        os.execv(str(OWW_VENV_PYTHON), argv)

    try:
        import openwakeword  # type: ignore
        from openwakeword.model import Model  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-voice-wake: openwakeword import failed: {exc}", flush=True)
        return run_phrase_loop() if stt_available() else run_energy_loop()

    if MODEL_PATH.is_file():
        print(f"aipc-voice-wake: loading user model {MODEL_PATH}", flush=True)
        oww = Model(wakeword_models=[str(MODEL_PATH)], inference_framework="onnx")
    else:
        durable = Path("/var/lib/aipc-voice/wake/models") / f"{PRETRAINED}_v0.1.onnx"
        if durable.is_file():
            print(f"aipc-voice-wake: loading {durable}", flush=True)
            oww = Model(wakeword_models=[str(durable)], inference_framework="onnx")
        else:
            print(f"aipc-voice-wake: loading pretrained {PRETRAINED}", flush=True)
            try:
                openwakeword.utils.download_models()
            except Exception:
                pass
            oww = Model(wakeword_models=[PRETRAINED], inference_framework="onnx")

    # openWakeWord is trained on 80 ms frames (1280 samples @ 16 kHz)
    frame_samples = 1280
    frame_bytes = frame_samples * 2
    proc = subprocess.Popen(
        [
            "arecord",
            "-f",
            "S16_LE",
            "-r",
            str(SAMPLE_RATE),
            "-c",
            "1",
            "-t",
            "raw",
            "-q",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_capture_env(),
    )
    assert proc.stdout is not None
    last = 0.0
    # Higher default threshold → fewer false positives
    threshold = float(os.environ.get("AIPC_WAKE_THRESHOLD", "0.6"))
    print(f"aipc-voice-wake: openWakeWord ready threshold={threshold}", flush=True)
    try:
        while True:
            if muted():
                time.sleep(0.2)
                proc.stdout.read(frame_bytes)
                continue
            data = proc.stdout.read(frame_bytes)
            if not data or len(data) < frame_bytes:
                continue
            try:
                import numpy as np  # type: ignore

                audio = np.frombuffer(data, dtype=np.int16)
            except Exception:
                audio = struct.unpack(f"<{len(data) // 2}h", data)
            prediction = oww.predict(audio)
            score = max(float(v) for v in prediction.values()) if prediction else 0.0
            now = time.monotonic()
            if score >= threshold and (now - last) >= COOLDOWN_S:
                last = now
                print(f"aipc-voice-wake: detected score={score:.2f} → once", flush=True)
                trigger_once()
    except KeyboardInterrupt:
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


def train_stub(samples_dir: Path, out_path: Path, label: str) -> int:
    """v0: write marker; custom phrases don't need ONNX training."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wavs = sorted(samples_dir.glob("*.wav"))
    if len(wavs) < 1:
        print("aipc-voice-train-wake: need at least 1 WAV in samples dir", file=sys.stderr)
        return 1
    marker = out_path.with_suffix(".txt")
    marker.write_text(
        f"label={label}\nsamples={len(wavs)}\n"
        "status=use-phrase-mode\n"
        "note=custom wake uses STT phrase match; edit /etc/aipc/wake/phrases\n"
    )
    print(f"aipc-voice-train-wake: wrote {marker}; prefer phrase mode for custom words")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--self-test", action="store_true")
    p.add_argument(
        "--print-policy",
        action="store_true",
        help="print effective arm/thrash/reprompt knobs as JSON and exit",
    )
    p.add_argument(
        "--mode",
        choices=("auto", "phrase", "energy", "openwakeword"),
        default="auto",
    )
    p.add_argument("--train", action="store_true", help="run train stub")
    p.add_argument("--samples", type=Path, default=Path("/var/lib/aipc-voice/wake/samples"))
    p.add_argument("--label", default="assistant")
    p.add_argument("--out", type=Path, default=MODEL_PATH)
    return p


def _self_test() -> int:
    phrases = ["嘿助理", "hey assistant", "你好助理", "小廢物"]
    assert _rms(b"\x00\x00" * 100) == 0.0
    loud = struct.pack("<h", 10000) * 200
    assert _rms(loud) > 1000
    assert phrase_hit("嘿助理", phrases) == "嘿助理"
    assert phrase_hit("嘿嘴。", phrases) == "嘿助理"
    assert phrase_hit("今天天气怎么样", phrases) is None
    assert phrase_hit("你好。", phrases) is None  # bare 你好 must NOT wake
    assert phrase_hit("你好助理", phrases) == "你好助理"
    assert phrase_hit("He助理。", phrases) == "嘿助理"
    assert phrase_hit("小飞幕听到了吗", phrases) == "小廢物"
    assert phrase_hit("请打开嘿助理功能", phrases) == "嘿助理"
    assert phrase_hit("嘿", phrases) is None
    # Anti-ghost: particle STT is never a clear phrase hit
    assert phrase_hit("我。", phrases) is None
    assert phrase_hit("我", phrases) is None
    assert classify_wake_text("我。", phrases)[0] == "fuzzy"
    assert classify_wake_text("嘿助理", phrases)[0] == "clear"
    assert classify_wake_text("今天天气怎么样", phrases)[0] == "none"
    d_low = decide_wake_arm(
        "fuzzy", 20, phrase=None, allow_fuzzy_promote=True, promote_score=90
    )
    assert d_low["arm"] is False and d_low["arm_reason"] == "ghost_suppressed"
    # Opt-in promote path (default allow is off; test with explicit promote_score)
    d_hi = decide_wake_arm(
        "fuzzy", 95, phrase=None, allow_fuzzy_promote=True, promote_score=90
    )
    assert d_hi["arm"] is True and d_hi["arm_reason"] == "fuzzy_promoted"
    d_clear = decide_wake_arm("clear", 0, phrase="嘿助理")
    assert d_clear["arm"] is True and d_clear["intentional"] is True
    d_ptt = decide_wake_arm("none", 0, ptt=True)
    assert d_ptt["arm"] is True and d_ptt["arm_reason"] == "ptt"
    assert junk_capture_action(intentional=True, reprompt_used=0) == "reprompt"
    assert junk_capture_action(intentional=True, reprompt_used=1) == "idle"
    assert junk_capture_action(intentional=False, reprompt_used=0) == "idle"
    assert next_mode_after_empty_capture("reprompt") == "command"
    assert next_mode_after_empty_capture("idle") == "listen"
    assert miss_backoff_seconds(1, base=6, cap=90) == 6.0
    assert miss_backoff_seconds(3, base=6, cap=90) == 12.0
    assert miss_backoff_seconds(10, base=6, cap=90) == 90.0
    pol = effective_wake_policy()
    assert pol["allow_fuzzy_promote"] is False or pol["promote_score"] >= 90
    assert pol["miss_backoff_base"] > 0
    # synthetic speech-shaped PCM scores above click
    frame = SAMPLE_RATE * FRAME_MS // 1000
    silence = struct.pack("<h", 0) * frame
    speech = struct.pack("<h", 8000) * frame
    click = speech + silence * 20
    spoken = silence * 2 + speech * 20 + silence * 2  # ~600ms speech
    assert score_wake_pcm(click, noise_floor=500, thr=2000) < score_wake_pcm(
        spoken, noise_floor=500, thr=2000
    )
    print("aipc-voice-wake: self-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.print_policy:
        print(json.dumps(effective_wake_policy(), ensure_ascii=False, indent=2))
        return 0
    if args.self_test:
        return _self_test()
    if args.train:
        return train_stub(args.samples, args.out, args.label)
    mode = args.mode
    if mode == "phrase":
        return run_phrase_loop()
    if mode == "energy":
        return run_energy_loop()
    if mode == "openwakeword":
        return run_openwakeword()
    # auto: phrase if STT up (custom + low FP + fast start); else OWW; else energy
    if stt_available():
        return run_phrase_loop()
    if OWW_VENV_PYTHON.is_file():
        try:
            return run_openwakeword()
        except Exception as exc:  # noqa: BLE001
            print(f"aipc-voice-wake: openwakeword failed: {exc}", flush=True)
    return run_energy_loop()


if __name__ == "__main__":
    raise SystemExit(main())
