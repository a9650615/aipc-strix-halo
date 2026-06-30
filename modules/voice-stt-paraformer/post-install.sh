#!/bin/sh
# post-install.sh — voice-stt-paraformer
# BUILD-TIME ONLY.
set -eu

systemctl enable aipc-paraformer.service
