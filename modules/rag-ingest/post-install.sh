#!/bin/sh
# post-install.sh — rag-ingest
# BUILD-TIME ONLY. No running services during image build.
set -eu

python3 -m venv /usr/lib/aipc-rag/venv
/usr/lib/aipc-rag/venv/bin/pip install --no-cache-dir -r /usr/lib/aipc-rag/requirements.txt

mkdir -p /var/lib/aipc-rag/state

systemctl enable aipc-rag-desktop.service
systemctl enable aipc-rag-code.service
# browser + screen-audio stay disabled until consent is recorded (D6/D7)
