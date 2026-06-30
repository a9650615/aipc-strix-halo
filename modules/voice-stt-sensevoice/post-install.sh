#!/bin/sh
# post-install.sh — voice-stt-sensevoice
# BUILD-TIME ONLY.
set -eu

systemctl enable aipc-sensevoice.service
