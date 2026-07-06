#!/bin/sh
# Static checks only (§9): pure-stdlib-boundary library, no daemon of its
# own to hardware-verify. Real OAuth/IMAP/CalDAV connections are exercised
# by the daily_assistant.py tool calls at runtime, not here.
set -eu
this_dir="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$this_dir/.disabled" ]; then
    echo "$(basename "$this_dir"): disabled (optional)" >&2
    exit 2
fi

pkg_dir="$this_dir/files/usr/lib/aipc-agent"
cfg="$this_dir/files/etc/aipc/agent/calendar.yaml"
fail() { echo "agent-tools-calendar: $*" >&2; exit 1; }

[ -f "$pkg_dir/aipc_agent_tools_calendar/backends.py" ] || fail "backends.py missing"
python3 -c "import ast; ast.parse(open('$pkg_dir/aipc_agent_tools_calendar/backends.py').read())" \
    || fail "syntax error in backends.py"
PYTHONPATH="$pkg_dir" python3 -c "from aipc_agent_tools_calendar.backends import self_test; self_test()" \
    >/dev/null || fail "self-test failed"

if python3 -c "import yaml" 2>/dev/null; then
    enabled="$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$cfg')) or {}
providers = cfg.get('providers') or {}
print(','.join(n for n, c in providers.items() if (c or {}).get('enabled')))
" 2>/dev/null)"
    if [ -z "$enabled" ]; then
        echo "agent-tools-calendar: no backend configured yet (INFO, not a failure)" >&2
    else
        echo "agent-tools-calendar: config OK, enabled backend(s): $enabled"
    fi
else
    echo "agent-tools-calendar: python3-yaml not present, skipped config-parse check (INFO)" >&2
fi

echo "agent-tools-calendar: static + self-test OK (render-verified; not hardware-verified — no live OAuth/IMAP/CalDAV connection exercised)"
