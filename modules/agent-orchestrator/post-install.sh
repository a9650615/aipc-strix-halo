#!/bin/sh
# post-install.sh — agent-orchestrator
# BUILD-TIME ONLY. No running services during image build.
set -eu

python3 -m venv /usr/lib/aipc-agent/venv
/usr/lib/aipc-agent/venv/bin/pip install --no-cache-dir -r /usr/lib/aipc-agent/requirements.txt

# A plain systemd unit runs as init_t without name_connect by default —
# without this the supervisor cannot reach LiteLLM (:4000, unreserved_port_t)
# or mem0 (:7000, gatekeeper_port_t). See selinux/aipc_agent_network.te.
# Policy-store only — safe at build time (no live services).
semodule -i /usr/share/selinux/packages/aipc_agent_network.pp

# Expose shipped /usr/lib/aipc-agent packages to the venv. This also makes the
# sibling agent-tools-files package importable when that module is rendered;
# missing is fine: files_read fails closed at runtime.
if [ -d /usr/lib/aipc-agent/aipc_agent ]; then
    /usr/lib/aipc-agent/venv/bin/python3 - <<'PY'
import site
from pathlib import Path

sp = Path(site.getsitepackages()[0])
(sp / "aipc-agent.pth").write_text("/usr/lib/aipc-agent\n")
PY
fi

systemctl enable aipc-agent-orchestrator.service

# Autonomous learning: idle episode → skill growth (default ON)
if [ -f /etc/systemd/system/aipc-self-improve.timer ] \
    || [ -f /usr/lib/systemd/system/aipc-self-improve.timer ]; then
    # Live hotfixes from a home-tree copy can land as user_home_t; fix label.
    if command -v restorecon >/dev/null 2>&1; then
        restorecon -F /etc/systemd/system/aipc-self-improve.service \
            /etc/systemd/system/aipc-self-improve.timer 2>/dev/null || true
        restorecon -F /etc/systemd/system/aipc-agent-orchestrator.service.d/zzz-skill-learn.conf \
            2>/dev/null || true
    fi
    systemctl enable aipc-self-improve.timer 2>/dev/null || true
fi

# Ensure on-box skill / episode dirs exist (process writes at runtime)
# skills-process: fallback for process teaching when /usr/share is read-only (ostree live)
mkdir -p /var/lib/aipc-agent/skills \
         /var/lib/aipc-agent/skills-process \
         /var/lib/aipc-agent/episodes \
         /var/lib/aipc-agent/learning \
         /var/lib/aipc-agent/browser-sandbox
chmod 755 /var/lib/aipc-agent/skills \
          /var/lib/aipc-agent/skills-process \
          /var/lib/aipc-agent/episodes \
          /var/lib/aipc-agent/learning 2>/dev/null || true
chmod 700 /var/lib/aipc-agent/browser-sandbox 2>/dev/null || true


# Enable quadlet units if present (enable only, init not running during build)
for unit in /etc/containers/systemd/aipc-agent-*.container; do
    [ -f "$unit" ] && systemctl enable "$(basename "$unit" .container).service" 2>/dev/null || true
done
