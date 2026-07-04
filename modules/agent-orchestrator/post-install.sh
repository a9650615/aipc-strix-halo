#!/bin/sh
# post-install.sh — agent-orchestrator
# BUILD-TIME ONLY. No running services during image build.
set -eu

python3 -m venv /usr/lib/aipc-agent/venv
/usr/lib/aipc-agent/venv/bin/pip install --no-cache-dir -r /usr/lib/aipc-agent/requirements.txt

# A plain systemd unit runs as init_t, which has no name_connect to
# unreserved_port_t by default — without this the supervisor's calls to
# the LiteLLM gateway (127.0.0.1:4000) hang. See selinux/aipc_agent_network.te
# for the full story and how this .pp was generated. Policy-store file
# operation, no live kernel/enforcement needed — safe at build time.
semodule -i /usr/share/selinux/packages/aipc_agent_network.pp

systemctl enable aipc-agent-orchestrator.service

# Enable quadlet units if present (enable only, init not running during build)
for unit in /etc/containers/systemd/aipc-agent-*.container; do
    [ -f "$unit" ] && systemctl enable "$(basename "$unit" .container).service" 2>/dev/null || true
done
