"""OAuth / CLI login helpers — mirrors official CodexBar login runners.

Official macOS app runs provider CLIs:

- Codex: ``codex login`` (CodexLoginRunner) → tokens in ``~/.codex/auth.json``
- Claude: ``claude auth login --claudeai`` (ClaudeLoginRunner)

We shell out the same way; the GUI only surfaces status + buttons.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("codexbar_gui.oauth_login")

# Official usage --source values (CLI + Preferences)
USAGE_SOURCES = ("auto", "oauth", "cli", "web", "api")
COOKIE_SOURCES = ("auto", "manual")


@dataclass
class LoginResult:
    ok: bool
    outcome: str  # success | timed_out | failed | missing_binary | launch_failed
    detail: str = ""
    auth_link: Optional[str] = None


@dataclass
class AuthStatus:
    provider: str
    method: str  # oauth | api_key | cookies | none | unknown
    label: str
    path: Optional[str] = None


def find_binary(name: str, extra: tuple[str, ...] = ()) -> Optional[str]:
    which = shutil.which(name)
    if which:
        return which
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / name,
        Path("/home/linuxbrew/.linuxbrew/bin") / name,
        Path("/usr/local/bin") / name,
        Path("/usr/bin") / name,
        *map(Path, extra),
    ]
    for p in candidates:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def auth_status_codex() -> AuthStatus:
    """Detect Codex OAuth session (official: ~/.codex/auth.json)."""
    homes = [
        Path(os.environ["CODEX_HOME"]) if os.environ.get("CODEX_HOME") else None,
        Path.home() / ".codex",
    ]
    for home in homes:
        if home is None:
            continue
        auth = home / "auth.json"
        if not auth.is_file():
            continue
        try:
            data = json.loads(auth.read_text())
        except (OSError, json.JSONDecodeError):
            return AuthStatus("codex", "oauth", f"auth.json unreadable ({auth})", str(auth))
        # Tokens present → logged in (do not surface secrets)
        tokens = data.get("tokens") or data.get("auth") or data
        has = bool(
            (isinstance(tokens, dict) and (tokens.get("access_token") or tokens.get("id_token")))
            or data.get("OPENAI_API_KEY")
            or data.get("access_token")
        )
        if has:
            email = ""
            acct = data.get("account") or data.get("user") or {}
            if isinstance(acct, dict):
                email = str(acct.get("email") or acct.get("email_address") or "")
            label = "OAuth signed in" + (f" · {email}" if email else f" · {auth}")
            return AuthStatus("codex", "oauth", label, str(auth))
        return AuthStatus("codex", "none", f"auth.json present but empty ({auth})", str(auth))
    return AuthStatus("codex", "none", "No ~/.codex/auth.json — run Login (OAuth)", None)


def auth_status_claude() -> AuthStatus:
    paths = [
        Path.home() / ".claude" / ".credentials.json",
        Path.home() / ".config" / "claude" / ".credentials.json",
        Path.home() / ".claude.json",
    ]
    for p in paths:
        if p.is_file():
            try:
                raw = p.read_text()
                if "accessToken" in raw or "access_token" in raw or "oauth" in raw.lower():
                    return AuthStatus("claude", "oauth", f"OAuth credentials · {p}", str(p))
                if "apiKey" in raw or "api_key" in raw or "sk-ant" in raw:
                    return AuthStatus("claude", "api_key", f"API key file · {p}", str(p))
            except OSError:
                pass
            return AuthStatus("claude", "unknown", f"Credentials file · {p}", str(p))
    return AuthStatus("claude", "none", "No Claude credentials — run Login (OAuth)", None)


def auth_status_for(provider: str) -> AuthStatus:
    pid = provider.lower().replace("_", "").replace("-", "")
    if pid in {"codex", "openai"}:
        # openai admin is api-key; still show codex oauth for codex
        if provider.lower() == "openai":
            return AuthStatus("openai", "api_key", "Uses Admin API key (set below)", None)
        return auth_status_codex()
    if pid == "claude":
        return auth_status_claude()
    if pid == "gemini":
        g = Path.home() / ".gemini"
        if g.exists():
            return AuthStatus("gemini", "oauth", f"Gemini config dir · {g}", str(g))
        return AuthStatus("gemini", "none", "No Gemini session found", None)
    if pid == "copilot":
        return AuthStatus("copilot", "oauth", "Device-flow / gh auth (see CLI)", None)
    if pid == "grok":
        # SuperGrok is browser cookies (web); API key is separate product surface
        if os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY"):
            return AuthStatus(
                "grok",
                "api_key",
                "XAI_API_KEY in env (API spend) · SuperGrok quota still needs source=web",
                None,
            )
        return AuthStatus(
            "grok",
            "web",
            "No OAuth — use source=web (SuperGrok cookies) or paste XAI_API_KEY",
            None,
        )
    if pid in {"zai", "glm", "zhipu"}:
        if os.environ.get("Z_AI_API_KEY") or os.environ.get("ZAI_API_KEY"):
            return AuthStatus("zai", "api_key", "Z_AI_API_KEY in env", None)
        return AuthStatus(
            "zai",
            "api_key",
            "API key only (z.ai / BigModel GLM) — no OAuth runner",
            None,
        )
    return AuthStatus(provider, "unknown", "API key or browser session (provider-specific)", None)


def run_codex_login(timeout: float = 180.0) -> LoginResult:
    """Official: ``codex login`` (browser OAuth)."""
    binary = find_binary("codex")
    if not binary:
        return LoginResult(False, "missing_binary", "codex CLI not found on PATH")
    try:
        proc = subprocess.run(
            [binary, "login"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        return LoginResult(False, "timed_out", out[-800:] or "login timed out")
    except OSError as exc:
        return LoginResult(False, "launch_failed", str(exc))
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode == 0:
        return LoginResult(True, "success", out[-800:] or "codex login OK")
    return LoginResult(False, "failed", out[-800:] or f"exit {proc.returncode}")


def run_claude_login(timeout: float = 180.0) -> LoginResult:
    """Official: ``claude auth login --claudeai``."""
    binary = find_binary("claude")
    if not binary:
        return LoginResult(False, "missing_binary", "claude CLI not found on PATH")
    cmd = [binary, "auth", "login", "--claudeai"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
        link = _first_url(out)
        return LoginResult(False, "timed_out", out[-800:] or "login timed out", link)
    except OSError as exc:
        return LoginResult(False, "launch_failed", str(exc))
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    link = _first_url(out)
    ok_markers = ("Successfully logged in", "Login successful", "Logged in successfully")
    if proc.returncode == 0 or any(m in out for m in ok_markers):
        return LoginResult(True, "success", out[-800:] or "claude login OK", link)
    return LoginResult(False, "failed", out[-800:] or f"exit {proc.returncode}", link)


def run_provider_login(provider: str, timeout: float = 180.0) -> LoginResult:
    pid = provider.lower()
    if pid == "codex":
        return run_codex_login(timeout=timeout)
    if pid == "claude":
        return run_claude_login(timeout=timeout)
    if pid == "gemini":
        binary = find_binary("gemini")
        if not binary:
            return LoginResult(False, "missing_binary", "gemini CLI not found")
        try:
            proc = subprocess.run(
                [binary, "auth", "login"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except Exception as exc:
            return LoginResult(False, "launch_failed", str(exc))
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return LoginResult(proc.returncode == 0, "success" if proc.returncode == 0 else "failed", out[-800:])
    return LoginResult(
        False,
        "failed",
        f"No OAuth login runner for {provider}. Use API key / cookies, or enable via CLI.",
    )


def _first_url(text: str) -> Optional[str]:
    import re

    m = re.search(r"https://[^\s\"'<>]+", text or "")
    return m.group(0) if m else None


def codex_login_status() -> str:
    binary = find_binary("codex")
    if not binary:
        return "codex CLI missing"
    try:
        proc = subprocess.run(
            [binary, "login", "status"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return ((proc.stdout or "") + (proc.stderr or "")).strip()[:400]
    except Exception as exc:
        return str(exc)
