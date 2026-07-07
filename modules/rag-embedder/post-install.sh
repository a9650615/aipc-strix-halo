#!/bin/sh
# post-install.sh — rag-embedder
# BUILD-TIME ONLY. No running services, no network beyond package repos.
set -eu

python3 -m venv /usr/lib/aipc-rag-embedder/venv
/usr/lib/aipc-rag-embedder/venv/bin/pip install --no-cache-dir -r /usr/lib/aipc-rag-embedder/requirements.txt

# SELinux: relabel venv entrypoints to bin_t so systemd's init_t -> service
# domain transition fires (see README "SELinux / init_t confinement").
if command -v semanage >/dev/null 2>&1 && command -v restorecon >/dev/null 2>&1; then
  semanage fcontext -a -t bin_t '/usr/lib/aipc-rag-embedder/venv/bin(/.*)?' 2>/dev/null || \
    semanage fcontext -m -t bin_t '/usr/lib/aipc-rag-embedder/venv/bin(/.*)?' 2>/dev/null || true
  restorecon -R /usr/lib/aipc-rag-embedder/venv/bin || true
elif command -v chcon >/dev/null 2>&1; then
  chcon -R -t bin_t /usr/lib/aipc-rag-embedder/venv/bin || true
fi

mkdir -p /var/lib/aipc-rag-embedder/hf-cache
# NOTE: bge-m3 weights (~4.3GB) must be pre-staged under this hf-cache before
# the service is useful -- it runs offline (HF_HUB_OFFLINE=1, SELinux denies
# egress). post-install is build-time with no HF access (§8), so this is a
# runtime/firstboot concern: `huggingface-cli download BAAI/bge-m3` into
# HF_HOME, like the LLM weights are pre-pulled. See README "bge-m3 staging".

systemctl enable aipc-rag-embedder.service
