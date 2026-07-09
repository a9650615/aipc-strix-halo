"""CodexBar GUI — QApplication entry point (delegates to ``__main__``)."""

from __future__ import annotations

import sys

from codexbar_gui.__main__ import entry_point


def main(argv: list[str] | None = None) -> int:
    return entry_point(argv)


if __name__ == "__main__":
    sys.exit(main())
