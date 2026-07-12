# Why — hermes-webui-module

Change 0009 stood up `nesquena/hermes-webui` (the web console for NousResearch
`hermes-agent`) as a hand-managed home checkout + a user systemd service created
live. That works but is not part of the image build: a rebuilt/re-provisioned
machine would not bring it back, and a crash-reboot already proved the plain
`ctl.sh` launch does not persist.

We want hermes-webui to be a first-class, reproducible part of the system: a repo
module that a rebuilt bootc/ansible image brings up automatically.

The catch — hermes-webui **self-updates (git-based)** and is **deeply coupled to
`hermes-agent`**: `api/config.py` injects the agent dir onto `sys.path` and
imports agent modules in-process (`hermes_cli`, `run_agent`, `agent.models_dev`),
so the server runs inside the **agent venv** (`~/.hermes/hermes-agent/venv`,
Python 3.11, which already carries pyyaml + cryptography). hermes-agent itself is
a user-home checkout the user patches locally — it is **not** baked into the
image either. Freezing a self-updating, home-coupled app into read-only
`/usr/lib` fights all of that.

So this module owns the **integration**, not a frozen copy: it ships the service
unit, portal card, and a first-boot setup that provisions the home checkout at a
pinned ref — consistent with how hermes-agent already lives in home.
