"""On-box modular skill tree — machine growth never under the aipc git checkout.

Roots (default order):
  1. Writable machine root — path-harvest / self-learn (e.g. /var/lib/aipc-agent/skills)
  2. Optional user Hermes learned dir
  3. Read-only **process teaching** skills shipped by aipc
     (/usr/share/aipc-agent/skills-process) — tool-use procedures only,
     never domain answers or catalog site seeds.

The aipc project may maintain process teaching skills; it must not seed titles/cast.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

# Primary writable root for skills grown by this process (image-persistent var).
DEFAULT_ROOT = Path(os.environ.get("AIPC_SKILL_ROOT", "/var/lib/aipc-agent/skills"))

# Shipped teaching skills (tool procedures only). Image path + var fallback
# (ostree /usr may be read-only; live hotfix can land under /var/lib).
_PROCESS_CANDIDATES = (
    os.environ.get("AIPC_SKILL_PROCESS_ROOT", ""),
    "/usr/share/aipc-agent/skills-process",
    "/var/lib/aipc-agent/skills-process",
)


def process_skill_roots() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for raw in _PROCESS_CANDIDATES:
        raw = (raw or "").strip()
        if not raw:
            continue
        p = Path(raw)
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out

# Never treat these as skill roots (repo checkout / openspec).
_FORBIDDEN_MARKERS = (
    "/modules/agent-orchestrator",
    "/openspec/",
    "/.git/",
)


def _primary_home() -> Path:
    try:
        uids = [int(d) for d in os.listdir("/run/user") if d.isdigit() and int(d) >= 1000]
        if uids:
            import pwd

            return Path(pwd.getpwuid(min(uids)).pw_dir)
    except (OSError, KeyError, ValueError, ImportError):
        pass
    return Path(os.environ.get("HOME") or Path.home())


def skill_roots() -> list[Path]:
    """Ordered roots to scan. First is the preferred write target (machine growth)."""
    raw = (os.environ.get("AIPC_SKILL_ROOTS") or "").strip()
    if raw:
        roots = [Path(p).expanduser() for p in raw.split(":") if p.strip()]
    else:
        home = _primary_home()
        roots = [
            DEFAULT_ROOT,
            home / ".hermes" / "skills" / "aipc-learned",
            *process_skill_roots(),
        ]
    out: list[Path] = []
    for r in roots:
        s = str(r.resolve()) if r.exists() else str(r)
        if any(m in s for m in _FORBIDDEN_MARKERS):
            print(f"aipc-agent: refuse skill root in source tree: {r}", flush=True)
            continue
        out.append(r)
    return out or [DEFAULT_ROOT]


def write_root() -> Path:
    """Always write machine-grown skills under AIPC_SKILL_ROOT (not process share)."""
    root = DEFAULT_ROOT
    # If AIPC_SKILL_ROOTS overrides, first path is still the write target
    raw = (os.environ.get("AIPC_SKILL_ROOTS") or "").strip()
    if raw:
        root = Path(raw.split(":")[0].strip()).expanduser()
    s = str(root.resolve()) if root.exists() else str(root)
    if any(m in s for m in _FORBIDDEN_MARKERS):
        print(f"aipc-agent: skill save refused (source tree): {root}", flush=True)
        raise OSError(f"skill write root forbidden: {root}")
    # Never write into process teaching trees
    try:
        for pr in process_skill_roots():
            if pr.exists() and root.resolve() == pr.resolve():
                root = DEFAULT_ROOT
                break
    except OSError:
        pass
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff_-]+", "-", (text or "").strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")[:48]
    return s or f"skill-{int(time.time()) % 100000}"


def list_skills() -> list[dict[str, Any]]:
    """Return skill metas found under all roots (newest first within each)."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in skill_roots():
        if not root.is_dir():
            continue
        for meta_path in sorted(root.glob("*/meta.json"), reverse=True):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            sid = str(data.get("id") or meta_path.parent.name)
            if sid in seen:
                continue
            seen.add(sid)
            data = dict(data)
            data["id"] = sid
            data["path"] = str(meta_path.parent)
            data["skill_md"] = str(meta_path.parent / "SKILL.md")
            found.append(data)
    return found


def read_skill_body(skill: dict[str, Any]) -> str:
    p = Path(str(skill.get("skill_md") or ""))
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8")[:6000]
    except OSError:
        return ""


def match(query: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Cheap lexical match over tags/title/triggers/body (no model required)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    q_tokens = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", q))
    has_code = bool(re.search(r"[A-Za-z]{2,8}-?\d{2,5}", query or ""))
    scored: list[tuple[float, dict[str, Any]]] = []
    for sk in list_skills():
        body_snip = read_skill_body(sk)[:1500].lower()
        bag = " ".join(
            [
                str(sk.get("id") or ""),
                str(sk.get("title") or ""),
                " ".join(str(t) for t in (sk.get("tags") or [])),
                " ".join(str(t) for t in (sk.get("triggers") or [])),
                " ".join(str(t) for t in (sk.get("examples") or [])[:5]),
                body_snip,
            ]
        ).lower()
        score = 0.0
        for t in q_tokens:
            if t in bag:
                score += 1.0
        # whole query substring
        if len(q) >= 4 and q in bag:
            score += 2.0
        # code-like tokens (e.g. FNS-232) in meta/examples
        for m in re.findall(r"[A-Za-z]{2,8}-?\d{2,5}", query or ""):
            if m.lower() in bag or m.upper() in bag:
                score += 3.0
        # Product-code questions should recall catalog lookup skills even
        # without that exact code in examples (learned PATH for next codes).
        # Product-style codes often need tool lookup skills
        if has_code:
            for kw in (
                "lookup",
                "web",
                "tools",
                "product-code",
                "web_search",
                "browser_navigate",
                "procedure",
            ):
                if kw in bag:
                    score += 1.5
        if score > 0:
            scored.append((score, sk))
    scored.sort(key=lambda x: (-x[0], -float(x[1].get("updated_ts") or 0)))
    return [s for _, s in scored[: max(1, limit)]]


def format_for_prompt(skills: list[dict[str, Any]], *, max_chars: int = 2500) -> str:
    if not skills:
        return ""
    parts = [
        "Local skills learned on this machine (follow when relevant; "
        "they are user/machine-specific procedures):"
    ]
    budget = max_chars
    for sk in skills:
        body = read_skill_body(sk)
        title = sk.get("title") or sk.get("id")
        block = f"### {title}\n{body}\n"
        if len(block) > budget:
            block = block[:budget] + "\n…"
        parts.append(block)
        budget -= len(block)
        if budget <= 200:
            break
    return "\n".join(parts)


def save_skill(
    *,
    title: str,
    body: str,
    tags: list[str] | None = None,
    triggers: list[str] | None = None,
    examples: list[str] | None = None,
    source: str = "aipc-learn",
    session_id: str = "",
    skill_id: str | None = None,
) -> dict[str, Any] | None:
    """Write a modular skill folder under the machine skill root only."""
    title = (title or "").strip() or "learned-skill"
    body = (body or "").strip()
    if len(body) < 40:
        return None
    try:
        root = write_root()
    except OSError as exc:
        print(f"aipc-agent: skill save refused: {exc}", flush=True)
        return None
    sid = skill_id or _safe_slug(title)
    # Never overwrite process teaching skills with harvest
    if sid == "web-tool-use" or (source or "").startswith("aipc-process"):
        print(f"aipc-agent: refuse clobber process teaching skill id={sid}", flush=True)
        return None
    # merge if exists
    dest = root / sid
    dest.mkdir(parents=True, exist_ok=True)
    meta_path = dest / "meta.json"
    prev: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            prev = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}
    examples_m = list(prev.get("examples") or [])
    for e in examples or []:
        e = (e or "").strip()[:200]
        if e and e not in examples_m:
            examples_m.append(e)
    examples_m = examples_m[-12:]
    tags_m = list(dict.fromkeys([*(prev.get("tags") or []), *(tags or [])]))[:24]
    triggers_m = list(dict.fromkeys([*(prev.get("triggers") or []), *(triggers or [])]))[
        :24
    ]
    now = time.time()
    meta = {
        "id": sid,
        "title": title[:120],
        "tags": tags_m,
        "triggers": triggers_m,
        "examples": examples_m,
        "source": source,
        "session_id": session_id or prev.get("session_id") or "",
        "created_ts": float(prev.get("created_ts") or now),
        "updated_ts": now,
        "hits": int(prev.get("hits") or 0) + 1,
    }
    skill_md = dest / "SKILL.md"
    header = f"# {title}\n\n<!-- aipc-learned local skill; not part of aipc git -->\n\n"
    try:
        skill_md.write_text(header + body.strip() + "\n", encoding="utf-8")
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(meta_path)
    except OSError as exc:
        print(f"aipc-agent: skill save fail: {exc}", flush=True)
        return None
    meta["path"] = str(dest)
    meta["skill_md"] = str(skill_md)
    print(f"aipc-agent: skill saved id={sid} path={dest}", flush=True)
    return meta
