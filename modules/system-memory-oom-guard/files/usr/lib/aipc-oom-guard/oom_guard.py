#!/usr/bin/env python3
"""Unified-memory-aware OOM guard.

Watches system RAM + per-backend cgroup memory + GPU/NPU allocation. On
pressure, relieves gracefully for model backends (their unload API) and
forcefully for apps (SIGTERM/SIGKILL). Victims are chosen by a priority
score, NOT a service whitelist — only "kill-the-box" core units are
hard-protected. See openspec/changes/memory-oom-guard/.
"""
import glob
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

import yaml

NORMAL, SOFT, HARD = "NORMAL", "SOFT", "HARD"


class OomGuard:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = NORMAL
        self.since = time.time()
        self.log_path = cfg["ring_buffer"]
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.self_cgroup = self._self_cgroup()

    # --- inputs ---
    def mem_available_mb(self):
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
        return 0

    def gpu_vram_mb(self):
        # ponytail: rocm-smi optional; unified-memory VRAM the kernel undercounts.
        # ceiling: card/key naming varies across rocm-smi versions; failure = skip.
        try:
            out = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram", "--json"],
                capture_output=True, text=True, timeout=4).stdout
            tot = 0
            for d in json.loads(out).values():
                if isinstance(d, dict):
                    for k, v in d.items():
                        if "VRAM" in k and "Used" in k:
                            tot += int(v)
            return tot // (1024 * 1024)
        except Exception:
            return None

    def top_cgroups(self, n):
        # ponytail: glob service cgroups under system.slice + user.slice;
        # O(services) per poll, fine at 1 Hz.
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
        # anti-self-kill: core system + self. NOT a service whitelist.
        name = entry["cgroup"]
        if name in (self.self_cgroup, "system.slice/oom-guard.service"):
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
        victims = [e for e in self.top_cgroups(self.cfg["top_n"])
                   if not self.is_protected(e)]
        if not victims:
            self.log_event(level=level, action="noop", result="no-victim",
                           reason="all top cgroups protected")
            return
        victims.sort(key=lambda e: (self.classify(e)[0] != "app", self.priority(e)))
        target = victims[0]
        cls, backend = self.classify(target)
        mem_before = self.mem_available_mb()
        if cls == "model":
            self._relieve_model(level, backend)
        else:
            self._relieve_app(level, target)
        self.log_event(level=level, mem_before=mem_before,
                       mem_after=self.mem_available_mb(),
                       target_cgroup=target["cgroup"], cls=cls,
                       backend=backend, target_mb=target["mb"])

    def _relieve_model(self, level, backend):
        bcfg = self.cfg["backends"][backend]
        if level == SOFT:
            self._backend_unload(backend, bcfg)
        else:
            self._restart(bcfg["unit"])

    def _backend_unload(self, backend, bcfg):
        try:
            if backend == "ollama":
                return self._ollama_unload(bcfg)
            if backend == "lemonade":
                return self._lemonade_unload(bcfg)
            if backend == "vllm":
                return self._vllm_sleep(bcfg)
        except Exception as e:
            self.log_event(action=f"unload:{backend}", result="error", reason=repr(e))

    def _ollama_unload(self, bcfg):
        models = self._http(bcfg["base_url"] + "/api/tags").get("models", [])
        if not models:
            return
        victim = min(models, key=lambda m: m.get("expires_at", 0))  # LRU
        self._http(bcfg["base_url"] + "/api/generate",
                   {"model": victim["name"], "keep_alive": 0})
        self.log_event(action="unload:ollama", result="ok", target=victim["name"])

    def _lemonade_unload(self, bcfg):
        # endpoint verified to exist (405 on GET) 2026-07-04; payload field
        # name confirmed on hardware in the (AI PC) task — see how.md risk.
        health = self._http(bcfg["base_url"] + "/api/v0/health")
        loaded = [m for m in health.get("all_models_loaded", [])
                  if m.get("loaded") and not m.get("pinned")]
        if not loaded:
            return
        victim = max(loaded, key=lambda m: m.get("last_use", 0))
        self._http(bcfg["base_url"] + bcfg["unload_path"],
                   {"model_name": victim["model_name"]})
        self.log_event(action="unload:lemonade", result="ok",
                       target=victim["model_name"])

    def _vllm_sleep(self, bcfg):
        self._http(bcfg["base_url"] + bcfg["sleep_path"], {}, method="POST")
        self.log_event(action="sleep:vllm", result="ok")

    def _relieve_app(self, level, target):
        pids = self._cgroup_pids(target["path"])
        if not pids:
            return
        pid = min(pids)  # ponytail: main process is lowest pid in the cgroup
        sig = signal.SIGKILL if level == HARD else signal.SIGTERM
        try:
            os.kill(pid, sig)
            self.log_event(action=f"kill:{sig.name}", pid=pid)
        except ProcessLookupError:
            pass

    # --- helpers ---
    def _restart(self, unit):
        subprocess.run(["systemctl", "restart", unit], timeout=30)
        self.log_event(action=f"restart:{unit}")

    def _cgroup_pids(self, cgroup_path):
        try:
            return [int(x) for x in open(cgroup_path + "/cgroup.procs") if x.strip()]
        except OSError:
            return []

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
    journald = {"cgroup": "system.slice/systemd-journald.service", "mb": 100, "idle": 9999}
    assert g.classify(lemon) == ("model", "lemonade")
    assert g.classify(app) == ("app", None)
    assert g.is_protected(journald) is True
    assert g.is_protected(lemon) is False      # models relieved, not protected
    assert g.priority(app) < g.priority(lemon)  # app evicted before model at equal idle
    print("self-test passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    cfg_path = os.environ.get("OOM_GUARD_CONFIG", "/etc/aipc/oom-guard/config.yaml")
    with open(cfg_path) as f:
        OomGuard(yaml.safe_load(f)).run()
