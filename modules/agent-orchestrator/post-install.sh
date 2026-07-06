#!/bin/sh
# post-install.sh — agent-orchestrator
# BUILD-TIME ONLY. No running services during image build.
set -eu

python3 -m venv /usr/lib/aipc-agent/venv
/usr/lib/aipc-agent/venv/bin/pip install --no-cache-dir -r /usr/lib/aipc-agent/requirements.txt

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

# Enable quadlet units if present (enable only, init not running during build)
for unit in /etc/containers/systemd/aipc-agent-*.container; do
    [ -f "$unit" ] && systemctl enable "$(basename "$unit" .container).service" 2>/dev/null || true
done
