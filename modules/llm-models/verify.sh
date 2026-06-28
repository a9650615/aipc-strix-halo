#!/bin/sh
# verify.sh — llm-models
# Exits 0 on success; exits 1 with one-line stderr diagnosis on failure.
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

registry=/etc/aipc/models/models.yaml

[ -f "${registry}" ] || fail "llm-models: ${registry} not found"
[ -s "${registry}" ] || fail "llm-models: ${registry} is empty"

# YAML must parse; python3-yaml is in system-base
python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" "${registry}" \
  || fail "llm-models: ${registry} is not valid YAML"

# At minimum, every alias from CLAUDE.md §7 must be present
for alias in router-1b intent-3b main-70b coder-fast coder-strong coder-thinking embed-bge vlm-qwen2vl; do
  grep -q "alias: ${alias}" "${registry}" || fail "llm-models: missing required alias '${alias}'"
done
