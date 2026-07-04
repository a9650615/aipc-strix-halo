#!/usr/bin/env python3
"""Unified-memory-aware OOM guard (painless-soft / forceful-hard).

Memory is meant to be USED — fill the 128 GB before acting. SOFT relief is
painless (drop caches + unload only idle/non-pinned models, NEVER kill). HARD
relief (kill/restart) fires only at a true near-OOM floor. Victim selection is
by RSS-based priority (cgroup memory.current freshness = idle, + a model
restart-cost bias), NEVER by VmSize — on this box node/V8 and mmap-heavy
processes (baloo ~269 GB, claude/opencode ~78 GB) reserve huge virtual but
commit little real RAM, so VmSize picks the wrong victim. VmSize is logged
only. Whole user@<uid> sessions are protected (killing one logs you out);
individual apps under them are fair game.

KILL SWITCH: touch /etc/aipc/oom-guard.disabled to suspend (monitor only).
See openspec/changes/memory-oom-guard/.
"""
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request

NORMAL, SOFT, HARD = "NORMAL", "SOFT", "HARD"
DEFAULT_DISABLE_SENTINEL = "/etc/aipc/oom-guard.disabled"
_SESSION_RE = re.compile(r"user@\d+\.service$")


class OomGuard:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = NORMAL
        self.since = time.time()
        self.log_path = cfg["ring_buffer"]
        self.sentinel = cfg.get("disable_sentinel", DEFAULT_DISABLE_SENTINEL)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.self_cgroup = self._self_cgroup()

    # --- inputs ---
    def mem_available_mb(self):
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
        return 0

    def top_cgroups(self, n):
        # ponytail: victim metric is RSS (memory.current), not VmSize. This
        # box's node/V8 + mmap processes reserve huge virtual but little real
        # RAM; VmSize picks the wrong victim. memory.current is the real
        # resident cost of killing the cgroup. NOTE: model backends that map
        # weights into unified GPU/NPU memory may under-report here — SOFT
        # unloads them via the backend API (not this metric); HARD relies on
        # priority/idle, so an under-reported backend just ranks safe.
        entries = []
        for pat in ("/sys/fs/cgroup/system.slice/*.service",
                    "/sys/fs/cgroup/user.slice/**/*.service"):
            for svc in glob.glob(pat):
                cur = svc + "/memory.current"
                if not os.path.exists(cur):
                    continue
                try:
                    used = int(open(cur).read().strip())
                    idle = time.time() - os.path.getmtime(cur)
                except (OSError, ValueError):
                    continue
                if used == 0:
                    continue
                entries.append({"cgroup": svc.split("/sys/fs/cgroup/", 1)[1],
                                "path": svc, "mb": used // (1024 * 1024),
                                "idle": idle})
        entries.sort(key=lambda e: e["mb"], reverse=True)
        return entries[:n]

    # --- classification + priority ---
    def classify(self, entry):
        for backend, bcfg in self.cfg.get("backends", {}).items():
            if entry["cgroup"] == bcfg["cgroup"]:
                return ("model", backend)
        return ("app", None)

    def is_protected(self, entry):
        name = entry["cgroup"]
        if name in (self.self_cgroup, "system.slice/oom-guard.service"):
            return True
        # never target a whole user@<uid> session cgroup — killing it logs the
        # user out. Individual apps live under it in app.slice/ (different
        # basename) and remain eligible.
        if _SESSION_RE.search(name.split("/")[-1]):
            return True
        return any(p in name for p in self.cfg.get("protected_patterns", []))

    def priority(self, entry):
        # lower = evicted first: idle time, bumped up for models (restart cost)
        score = entry["idle"]
        if self.classify(entry)[0] == "model":
            score += self.cfg.get("model_protect_bias", 600)
        return score

    # --- relief ---
    def relieve(self, level):
        if level == SOFT and not self.cfg.get("dry_run"):
            self._relieve_soft()  # painless only — never kills
            return
        # dry_run (any level) or HARD: pick a victim by PRIORITY (idle-heavy
        # apps first, models carry a restart-cost bias) — NOT highest RSS.
        # An in-use service (fresh memory.current = low idle) ranks safe; a
        # long-idle hog ranks first. top_cgroups is already RSS-sorted but we
        # re-sort by priority for the decision.
        victims = [e for e in self.top_cgroups(self.cfg["top_n"])
                   if not self.is_protected(e)]
        if not victims:
            self.log_event(level=level, dry_run=bool(self.cfg.get("dry_run")),
                           action="noop", result="no-victim")
            return
        victims.sort(key=lambda e: (self.classify(e)[0] != "app", self.priority(e)))
        target = victims[0]
        cls, backend = self.classify(target)
        pid = self._cgroup_main_pid(target["path"])
        detail = self._proc_detail(pid)
        if self.cfg.get("dry_run"):
            self.log_event(level=level, dry_run=True, action="would-act", would=cls,
                           target_cgroup=target["cgroup"], target_mb=target["mb"], **detail)
            return
        # HARD: forceful
        mem_before = self.mem_available_mb()
        if cls == "model":
            self._restart(self.cfg["backends"][backend]["unit"])
            action = f"restart:{backend}"
        else:
            self._relieve_app(target)
            action = "kill:app"
        mem_after = self.mem_available_mb()
        self.log_event(level=HARD, action=action, mem_before=mem_before,
                       mem_after=mem_after, target_cgroup=target["cgroup"],
                       cls=cls, backend=backend, target_mb=target["mb"], **detail)
        self._notify(f"OOM guard: {action}",
                     f"mem free {mem_before}->{mem_after}MB | "
                     f"{target['cgroup']} (RSS {target['mb']}MB)")

    def _relieve_soft(self):
        # painless: drop page cache (kernel rebuilds it, user can't tell) +
        # unload ONE idle/non-pinned model. No process is killed in SOFT.
        self._drop_caches()
        self._unload_idle_model()

    def _drop_caches(self):
        try:
            with open("/proc/sys/vm/drop_caches", "w") as f:
                f.write("1")
            self.log_event(level=SOFT, action="drop_caches", result="ok")
        except OSError as e:
            self.log_event(level=SOFT, action="drop_caches", result="error", reason=repr(e))

    def _unload_idle_model(self):
        # unload one idle non-pinned loaded model from whichever backend has
        # one. Best-effort; backends not running are skipped.
        for backend, bcfg in self.cfg.get("backends", {}).items():
            try:
                if backend == "ollama":
                    models = self._http(bcfg["base_url"] + "/api/tags").get("models", [])
                    if models:
                        v = min(models, key=lambda m: m.get("expires_at", 0))
                        self._http(bcfg["base_url"] + "/api/generate",
                                   {"model": v["name"], "keep_alive": 0})
                        self.log_event(level=SOFT, action="unload:ollama", result="ok", target=v["name"])
                        return
                elif backend == "lemonade":
                    # payload verified 2026-07-05: POST {model_name} -> 200.
                    # /api/v0/load times out (>90s); rely on on-demand auto-load
                    # to restore. SOFT unloads only idle non-pinned.
                    health = self._http(bcfg["base_url"] + "/api/v0/health")
                    loaded = [m for m in health.get("all_models_loaded", [])
                              if m.get("loaded") and not m.get("pinned")]
                    if loaded:
                        v = max(loaded, key=lambda m: m.get("last_use", 0))
                        self._http(bcfg["base_url"] + bcfg["unload_path"],
                                   {"model_name": v["model_name"]})
                        self.log_event(level=SOFT, action="unload:lemonade", result="ok", target=v["model_name"])
                        return
                # vllm: no per-idle unload; HARD falls back to systemctl restart.
            except Exception as e:
                self.log_event(level=SOFT, action=f"probe:{backend}", result="error", reason=repr(e))
        self.log_event(level=SOFT, action="unload", result="no-idle-model")

    def _relieve_app(self, target):
        pid = self._cgroup_main_pid(target["path"])
        if not pid:
            return
        try:
            os.kill(pid, signal.SIGKILL)  # HARD only
            self.log_event(action="kill:SIGKILL", pid=pid, **self._proc_detail(pid))
        except ProcessLookupError:
            pass

    # --- helpers ---
    def _restart(self, unit):
        subprocess.run(["systemctl", "restart", unit], timeout=30)
        self.log_event(action=f"restart:{unit}")

    def _cgroup_main_pid(self, cgroup_path):
        try:
            pids = [int(x) for x in open(cgroup_path + "/cgroup.procs") if x.strip()]
            return min(pids) if pids else None
        except OSError:
            return None

    def _proc_detail(self, pid):
        # log-only memory breakdown — distinguishes a real hog (high RssAnon)
        # from a virtual-reserve phantom (high VmSize, low RssAnon, e.g.
        # opencode/baloo/claude). NEVER feeds a decision; see top_cgroups.
        if not pid:
            return {}
        try:
            s = {}
            for l in open(f"/proc/{pid}/status"):
                if ":" in l:
                    k, v = l.split(":", 1); s[k.strip()] = v.strip()
            cmd = open(f"/proc/{pid}/cmdline").read().replace("\x00", " ").strip()[:80]
            return {"cmd": cmd, "VmSize": s.get("VmSize", "?"),
                    "RssAnon": s.get("RssAnon", "?"), "RssFile": s.get("RssFile", "?"),
                    "RssShmem": s.get("RssShmem", "?")}
        except OSError:
            return {}

    def _primary_uid(self):
        # resolve the desktop user dynamically — never hardcode a username.
        try:
            uids = [int(d) for d in os.listdir("/run/user") if d.isdigit()]
            return min((u for u in uids if u >= 1000), default=None)
        except OSError:
            return None

    def _notify(self, title, body):
        # desktop notification on FORCEFUL action only (HARD), so the user
        # sees the guard acted. Sent into the primary user's Plasma session.
        # ponytail ceiling: DISPLAY/WAYLAND/DBUS paths assume a single-user
        # Plasma login; if notify-send fails we just log it and never block.
        uid = self._primary_uid()
        if not uid:
            return
        import pwd
        try:
            user = pwd.getpwuid(uid).pw_name
        except KeyError:
            return
        env = {"XDG_RUNTIME_DIR": f"/run/user/{uid}",
               "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
               "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "PATH": "/usr/bin:/bin"}
        try:
            subprocess.run(["runuser", "-u", user, "--", "notify-send",
                            "--icon=dialog-warning", "--urgency=critical",
                            title, body[:200]],
                           env=env, timeout=5, capture_output=True)
        except Exception as e:
            self.log_event(action="notify", result="error", reason=repr(e))

    def _self_cgroup(self):
        try:
            return open("/proc/self/cgroup").read().split(":")[-1].strip().lstrip("/")
        except OSError:
            return ""

    def _http(self, url, payload=None, method=None):
        data = json.dumps(payload).encode() if payload is not None else None
        m = method or ("POST" if payload is not None else "GET")
        req = urllib.request.Request(url, data=data, method=m,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read()
            return json.loads(body) if body[:1] in b"{[" else {}

    def log_event(self, **fields):
        fields["ts"] = time.time()
        line = json.dumps(fields, default=str)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")
        print(line, file=sys.stderr, flush=True)  # journald captures stderr

    # --- state machine ---
    def step(self):
        if os.path.exists(self.sentinel):
            return  # kill switch active: monitor only, never act
        mem = self.mem_available_mb()
        soft, hard = self.cfg["soft_bar_mb"], self.cfg["hard_bar_mb"]
        elapsed = time.time() - self.since
        if mem < hard and elapsed >= self.cfg["t_hard"]:
            self._transition(HARD, mem)
        elif mem < soft and elapsed >= self.cfg["t_soft"]:
            self._transition(SOFT, mem)
        elif mem >= soft and self.state != NORMAL:
            self._transition(NORMAL, mem)

    def _transition(self, new_state, mem):
        old = self.state
        self.state = new_state
        self.since = time.time()
        if new_state in (SOFT, HARD):
            self.relieve(new_state)
        self.log_event(event="transition", frm=old, to=new_state, mem=mem)

    def run(self):
        while True:
            try:
                self.step()
            except Exception as e:
                self.log_event(event="error", reason=repr(e))
            time.sleep(self.cfg["poll_interval"])


def self_test():
    """ponytail: one runnable check — classify/priority/protected logic."""
    cfg = {"ring_buffer": "/tmp/oom-guard-test.jsonl",
           "backends": {"lemonade": {"cgroup": "system.slice/lemonade.service"},
                        "ollama": {"cgroup": "system.slice/ollama.service"}},
           "protected_patterns": ["systemd-", "dbus", "journald", "login",
                                  "display-manager", "oom-guard"],
           "model_protect_bias": 600}
    g = OomGuard(cfg)
    g.self_cgroup = "system.slice/oom-guard.service"
    lemon = {"cgroup": "system.slice/lemonade.service", "mb": 9000, "idle": 5}
    app = {"cgroup": "user.slice/user-1000.slice/user@1000.service/"
                     "app.slice/firefox.service", "mb": 4000, "idle": 5}
    session = {"cgroup": "user.slice/user-1000.slice/user@1000.service", "mb": 7222, "idle": 5}
    journald = {"cgroup": "system.slice/systemd-journald.service", "mb": 100, "idle": 9999}
    assert g.classify(lemon) == ("model", "lemonade")
    assert g.classify(app) == ("app", None)
    assert g.is_protected(journald) is True
    assert g.is_protected(session) is True      # whole session must be protected
    assert g.is_protected(app) is False          # individual app under it is eligible
    assert g.is_protected(lemon) is False
    assert g.priority(app) < g.priority(lemon)
    print("self-test passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    cfg_path = os.environ.get("OOM_GUARD_CONFIG", "/etc/aipc/oom-guard/config.yaml")
    import yaml
    with open(cfg_path) as f:
        OomGuard(yaml.safe_load(f)).run()
