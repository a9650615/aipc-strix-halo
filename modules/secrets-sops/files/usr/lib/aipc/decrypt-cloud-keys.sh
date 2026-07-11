#!/bin/sh
# Runtime decryption of cloud LLM API keys. Invoked by aipc-decrypt-cloud-keys.service
# before litellm.service. Exits 0 (not fail) when src or key absent — cloud keys
# are optional per cloud-llm-fallback design (D-non-goal "Cloud keys optional").
set -eu

src=/etc/aipc/secrets/cloud-llm.yaml
dst=/etc/aipc/env.d/llm-litellm/cloud-keys.env

[ -f "$src" ] || { echo "no $src; skipping" >&2; exit 0; }
[ -f /etc/aipc/age.key ] || { echo "no /etc/aipc/age.key; cannot decrypt" >&2; exit 0; }

mkdir -p "$(dirname "$dst")"
umask 077
SOPS_AGE_KEY_FILE=/etc/aipc/age.key sops --decrypt "$src" | \
    awk -F': ' '
        $1=="anthropic_api_key" { print "ANTHROPIC_API_KEY=" $2 }
        $1=="openai_api_key"    { print "OPENAI_API_KEY="    $2 }
        $1=="gemini_api_key"    { print "GEMINI_API_KEY="    $2 }
        $1=="zai_api_key"       { print "Z_AI_API_KEY="      $2 }
    ' > "$dst"
chmod 0600 "$dst"
