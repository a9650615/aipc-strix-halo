#!/usr/bin/env python3
"""Legacy entrypoint — delegates to aipc-power-agent.

Kept so live-hotfix paths and old unit files that still point here keep working
until the next image ships only aipc-power-agent.service.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

AGENT = Path("/usr/lib/aipc-power-agent/agent.py")
# Repo / offline: sibling relative to this file's installed layout.
if not AGENT.is_file():
    AGENT = Path(__file__).resolve().parents[1] / "aipc-power-agent" / "agent.py"

if not AGENT.is_file():
    print(f"aipc-power-agent not found (looked for {AGENT})", file=sys.stderr)
    sys.exit(1)

# Expose PowerGuard for tests that import this module path.
_agent_dir = str(AGENT.parent)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)
from backfeed import BackfeedGuard as PowerGuard  # noqa: E402,F401
from backfeed import BackfeedGuard  # noqa: E402,F401

if __name__ == "__main__":
    sys.argv[0] = str(AGENT)
    runpy.run_path(str(AGENT), run_name="__main__")
