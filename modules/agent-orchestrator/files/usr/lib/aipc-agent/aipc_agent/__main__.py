"""python -m aipc_agent self-improve | learn-stats"""

from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m aipc_agent self-improve [--hours N] [--max N]")
        print("       python -m aipc_agent self-improve --stats")
        return 0
    cmd = argv[0]
    rest = argv[1:]
    if cmd in ("self-improve", "self_improve", "improve"):
        from aipc_agent.self_improve import main as improve_main

        return improve_main(rest)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
