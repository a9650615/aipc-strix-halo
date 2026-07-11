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

# Standing local + gateway aliases (trimmed set + phase-2 embed + phase-4 VLM).
# Old qwen2.5 family (router-1b, intent-3b, main-70b, …) was deliberately cut.
for alias in resident-small coder-agentic ornith-35b embed-bge vlm-qwen2vl; do
  grep -q "alias: ${alias}" "${registry}" || fail "llm-models: missing required alias '${alias}'"
done

# Compact lane self-unloads after five minutes idle.
python3 - "${registry}" <<'PY' || fail "llm-models: coder-compact idle_unload_after_s missing or not 300"
import sys, yaml
data = yaml.safe_load(open(sys.argv[1]))
for entry in data.get("models", []):
    if entry.get("alias") == "coder-compact":
        raise SystemExit(0 if entry.get("idle_unload_after_s") == 300 else 1)
raise SystemExit(1)
PY
