#!/bin/sh
set -eu
rpm-ostree install -y rocm-smi amd-smi rocm-hip-runtime
