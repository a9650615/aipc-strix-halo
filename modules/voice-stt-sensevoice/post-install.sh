#!/bin/sh
# post-install.sh — voice-stt-sensevoice
# BUILD-TIME ONLY. No running services, no GPU/NPU, network limited to
# package/pip repos (CLAUDE.md §8). Model weights are NOT fetched here —
# funasr.AutoModel downloads iic/SenseVoiceSmall on first run into
# MODELSCOPE_CACHE (see the systemd unit), the first time the service starts
# with network available.
set -eu

python3 -m venv /usr/lib/aipc-voice/venv
/usr/lib/aipc-voice/venv/bin/pip install --no-cache-dir -r /usr/lib/aipc-voice/requirements.txt

# SELinux: relabel venv entrypoints to bin_t so systemd can EXEC them.
# Without this, uvicorn lands as lib_t / var_lib_t and the unit dies with
# status=203/EXEC ("Permission denied") — same class as memory-mem0 /
# rag-embedder. Best-effort: build env may lack semanage/restorecon.
if command -v semanage >/dev/null 2>&1 && command -v restorecon >/dev/null 2>&1; then
  semanage fcontext -a -t bin_t '/usr/lib/aipc-voice/venv/bin(/.*)?' 2>/dev/null || \
    semanage fcontext -m -t bin_t '/usr/lib/aipc-voice/venv/bin(/.*)?' 2>/dev/null || true
  restorecon -R /usr/lib/aipc-voice/venv/bin || true
elif command -v chcon >/dev/null 2>&1; then
  chcon -R -t bin_t /usr/lib/aipc-voice/venv/bin || true
fi

mkdir -p /var/lib/aipc-voice/models

systemctl enable aipc-voice-stt-sensevoice.service
