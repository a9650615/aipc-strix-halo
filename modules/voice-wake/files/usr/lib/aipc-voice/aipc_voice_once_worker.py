"""Background aipc-voice-once / stream worker for voice-wake."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path

ONCE_CMD = os.environ.get("AIPC_VOICE_ONCE", "/usr/bin/aipc-voice-once")
STREAM_CMD = os.environ.get("AIPC_VOICE_STREAM_CMD", "/usr/bin/aipc-voice-stream")

try:
    import aipc_voice_ux as voice_ux  # type: ignore
except Exception:
    voice_ux = None


def _ux(state: str, detail: str = "", **kw) -> None:
    if voice_ux is None:
        return
    try:
        voice_ux.announce(state, detail, **kw)
    except Exception as exc:  # noqa: BLE001
        print(f"aipc-voice-wake: ux fail: {exc}", flush=True)


def desktop_user_env() -> dict[str, str]:
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


def kill_process_group(proc: subprocess.Popen, reason: str = "") -> None:
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
    """Background aipc-voice-once runner (no mic). Latest job wins."""

    def __init__(self, on_finished=None) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._gen = 0
        self._on_finished = on_finished

    def busy(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def cancel_speech(self, reason: str = "speech-cancel") -> bool:
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
            kill_process_group(proc, reason)
        self.cancel_speech(f"with-task:{reason}")
        return live

    def submit_wav(self, wav_path: str, text: str | None = None) -> None:
        self.cancel(reason="new-job")
        gen = self._gen

        def _run() -> None:
            env = desktop_user_env()
            use_stream = env.get(
                "AIPC_VOICE_STREAM", os.environ.get("AIPC_VOICE_STREAM", "0")
            )
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
                    kill_process_group(proc, "superseded-at-start")
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
                ok = rc in (0, 2, 3, 4)
                if self._on_finished is not None:
                    try:
                        self._on_finished(ok, rc=rc)
                    except TypeError:
                        try:
                            self._on_finished(ok)
                        except Exception as exc:  # noqa: BLE001
                            print(
                                f"aipc-voice-wake: on_finished failed: {exc}",
                                flush=True,
                            )
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"aipc-voice-wake: on_finished failed: {exc}", flush=True
                        )
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


def trigger_once(
    *, wait: bool = False, timeout: float = 180.0, wav: str | None = None
) -> int:
    env = desktop_user_env()
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
            r = subprocess.run(
                argv, env=env, stdout=log_f, stderr=log_f, timeout=timeout
            )
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


# Legacy aliases
_desktop_user_env = desktop_user_env
_kill_process_group = kill_process_group
