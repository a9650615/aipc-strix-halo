#!/bin/sh
# post-install.sh — memory-mem0
# BUILD-TIME ONLY. No running services, no network beyond package repos.
set -eu

python3 -m venv /usr/lib/aipc-mem0/venv
/usr/lib/aipc-mem0/venv/bin/pip install --no-cache-dir -r /usr/lib/aipc-mem0/requirements.txt

# SELinux: relabel venv entrypoints to bin_t so systemd's init_t -> service
# domain transition fires (see README "SELinux / init_t confinement").
# Without this the service runs in init_t and is denied outbound loopback +
# oneDNN JIT mmap-exec. Best-effort: build env may lack semanage/restorecon.
if command -v semanage >/dev/null 2>&1 && command -v restorecon >/dev/null 2>&1; then
  semanage fcontext -a -t bin_t '/usr/lib/aipc-mem0/venv/bin(/.*)?' 2>/dev/null || \
    semanage fcontext -m -t bin_t '/usr/lib/aipc-mem0/venv/bin(/.*)?' 2>/dev/null || true
  restorecon -R /usr/lib/aipc-mem0/venv/bin || true
elif command -v chcon >/dev/null 2>&1; then
  chcon -R -t bin_t /usr/lib/aipc-mem0/venv/bin || true
fi

mkdir -p /var/lib/aipc-mem0
chmod +x /usr/lib/aipc-mem0/aipc-mem0-state-dir-setup

systemctl enable aipc-mem0-state-dir.service
systemctl enable aipc-mem0.service
