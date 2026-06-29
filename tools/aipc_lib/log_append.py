from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

ROLES = ("大哥", "副官", "執行兵")

_DEFAULT_LOG = Path(__file__).resolve().parents[2] / "docs" / "agent-log.md"
_FIELDS = ("date", "role", "model", "run_label", "spec_tasks", "sha_range", "outcome")


def _validate(date: str, role: str, model: str, run_label: str, spec_tasks: str, sha_range: str, outcome: str) -> None:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    try:
        _dt.date.fromisoformat(date)
    except (TypeError, ValueError) as e:
        raise ValueError(f"date must be ISO-8601 YYYY-MM-DD, got {date!r}") from e
    for name, val in zip(_FIELDS[2:], (model, run_label, spec_tasks, sha_range, outcome)):
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"{name} must be a non-empty string, got {val!r}")


def append_row(
    date: str,
    role: str,
    model: str,
    run_label: str,
    spec_tasks: str,
    sha_range: str,
    outcome: str,
    log_path: Path | str | None = None,
) -> str:
    _validate(date, role, model, run_label, spec_tasks, sha_range, outcome)
    line = f"| {date} | {role} | {model} | {run_label} | {spec_tasks} | {sha_range} | {outcome} |\n"
    path = Path(log_path) if log_path is not None else _DEFAULT_LOG

    content = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = content.splitlines(keepends=True)

    insert_at = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("| "):
            insert_at = i + 1
            break

    lines.insert(insert_at, line)
    new_content = "".join(lines)
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    os.replace(tmp, path)
    return line
