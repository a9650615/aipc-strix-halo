# Tasks for memory-oom-guard

- [ ] Create module skeleton `modules/system-memory-oom-guard/` with README, packages.txt
- [ ] Implement pressure monitor + hysteresis state machine (`files/src/oom_guard.py`)
- [ ] Implement cgroup classifier + priority scorer (victim selection)
- [ ] Implement backend control actors (Ollama `keep_alive:0`, Lemonade `POST /api/v0/unload`, vLLM `/sleep`)
- [ ] Implement app SIGTERM→SIGKILL actor with anti-self-kill guards
- [ ] Implement structured event logging (journald + `events.jsonl` ring buffer)
- [ ] Create deployment unit (systemd service) + `post-install.sh`
- [ ] Add `verify.sh` (static + render checks; cgroup/sysfs paths exist)
- [ ] (AI PC) Hardware-verify Lemonade `/api/v0/unload` payload signature and calibrate thresholds
- [ ] Register guard in `ops-doctor` `services.yaml` (optional panel)
- [ ] Run `tools/aipc render bootc` + `render ansible --check` (render-verified)
