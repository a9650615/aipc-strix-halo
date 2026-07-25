#!/bin/sh
# Headless CodexBar usage server (HTML + /usage on :8080).
# Image path: /usr/lib/codexbar-gui. Live-hotfix: set CODEXBAR_GUI_SRC to the
# repo files/usr/lib/codexbar-gui tree (prepended to PYTHONPATH).
set -eu
export PATH="${HOME}/.local/bin:/usr/lib/aipc/tools/.venv/bin:/usr/local/bin:/usr/bin:/bin${PATH:+:$PATH}"

_py_path="/usr/lib/codexbar-gui"
if [ -n "${CODEXBAR_GUI_SRC:-}" ]; then
  _py_path="${CODEXBAR_GUI_SRC}:${_py_path}"
fi
export PYTHONPATH="${_py_path}${PYTHONPATH:+:$PYTHONPATH}"

if [ -x /usr/lib/aipc/tools/.venv/bin/python ]; then
  PY=/usr/lib/aipc/tools/.venv/bin/python
else
  PY=python3
fi

exec "$PY" -m codexbar_gui --web-only --host 127.0.0.1 --web-port 8080
