"""Cursor provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/Cursor/CursorProvider.swift
- Sources/CodexBarCore/Providers/Cursor/CursorCookieAuth.swift
- Sources/CodexBarCore/Providers/Cursor/CursorUsageAPI.swift

References:
- API: https://cursor.com/api/usage
- Auth: Browser cookies (cursor_session, cursor_refresh) or manual Cookie header
- Linux Support: partial (API works, cookie extraction requires browser context)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .base import (
    AuthError,
    BaseProvider,
    ConfigError,
    NetworkError,
    ProviderError,
    ProviderIdentitySnapshot,
    ProviderStatus,
    RateWindow,
    UsageSnapshot,
)

logger = logging.getLogger(__name__)

# Cursor API base URL.
CURSOR_API_BASE = "https://cursor.com/api"
# Usage endpoint.
CURSOR_USAGE_PATH = "/usage"
# Cursor CLI auth token file (macOS / Windows / Linux).
CURSOR_CLI_STATE_PATHS = [
    Path.home() / ".cursor" / "state.json",
    Path.home() / ".config" / "cursor" / "state.json",
    Path.home() / "Library" / "Application Support" / "Cursor" / "Local Storage" / "leveldb",
]
# Cursor session cookie names.
CURSOR_COOKIE_NAMES = ["cursor_session", "cursor_refresh", "cursor_token"]


class CursorProvider(BaseProvider):
    """Cursor provider using API and cookie-based authentication.

    Ported from: Sources/CodexBarCore/Providers/Cursor/CursorProvider.swift

    Supports:
    - Cursor API usage endpoint (/api/usage)
    - Browser cookie authentication (cursor_session / cursor_refresh)
    - Cursor CLI state file extraction
    - Manual cookie configuration via environment variable

    Linux Support: partial (API fully works, cookie extraction from browser is limited)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cookies: Optional[str] = None,
        base_url: str = CURSOR_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Cursor provider.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorProvider.swift:init

        Args:
            api_key: Pre-extracted bearer token (optional).
            cookies: Cookie header string (e.g. "cursor_session=...; cursor_refresh=...").
            base_url: Base URL for Cursor API.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="cursor",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self.cookies = cookies
        self._logger = logging.getLogger(f"providers.cursor")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch Cursor usage data.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorProvider.swift:fetchUsage()

        Strategy:
        1. Obtain authentication (cookies, CLI state, or env var).
        2. Query Cursor API for usage data.
        3. Parse usage windows and identity.

        Returns:
            UsageSnapshot with primary rate window and identity.

        Raises:
            AuthError: If no valid authentication source found.
            NetworkError: If API request fails.
        """
        self.status = ProviderStatus.READY

        try:
            # Build authentication headers.
            headers = await self._build_auth_headers()

            # Fetch usage from Cursor API.
            usage_data = await self._fetch_usage(headers)

            primary_window = self._parse_usage(usage_data)
            identity = self._parse_identity(usage_data)

            return UsageSnapshot(
                primary=primary_window,
                identity=identity,
                updated_at=datetime.now(timezone.utc),
            )

        except ProviderError:
            raise
        except Exception as e:
            self.status = ProviderStatus.ERROR
            self.last_error = ProviderError(f"Failed to fetch Cursor usage: {e}")
            raise self.last_error

    async def _build_auth_headers(self) -> Dict[str, str]:
        """Build authentication headers for Cursor API.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorCookieAuth.swift:_buildAuthHeaders()

        Tries multiple auth sources in order:
        1. Explicit cookies parameter.
        2. Cursor CLI state files.
        3. CURSOR_COOKIES environment variable.
        4. CURSOR_API_KEY / CURSOR_TOKEN environment variable.

        Returns:
            Headers dictionary with authentication.

        Raises:
            AuthError: If no valid authentication source.
        """
        # Check explicit cookies parameter.
        if self.cookies:
            headers = self._create_auth_headers()
            headers["Cookie"] = self.cookies
            return headers

        # Try extracting from Cursor CLI state files.
        cookies = self._extract_cookies_from_state()
        if cookies:
            headers = self._create_auth_headers()
            headers["Cookie"] = cookies
            return headers

        # Check environment variables.
        env_cookies = os.environ.get("CURSOR_COOKIES")
        if env_cookies:
            headers = self._create_auth_headers()
            headers["Cookie"] = env_cookies
            return headers

        env_token = os.environ.get("CURSOR_API_KEY") or os.environ.get("CURSOR_TOKEN")
        if env_token:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {env_token}"
            return headers

        # If using the api_key field, treat it as a bearer token.
        if self.api_key:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {self.api_key}"
            return headers

        self.status = ProviderStatus.NO_CREDENTIALS
        raise AuthError(
            "No Cursor authentication found. Set CURSOR_COOKIES, CURSOR_TOKEN, "
            "or configure Cursor CLI."
        )

    def _extract_cookies_from_state(self) -> Optional[str]:
        """Extract Cursor cookies from CLI state files.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorCookieAuth.swift:_extractCookiesFromState()

        Reads JSON state files and extracts session/refresh tokens.

        Returns:
            Cookie header string or None.
        """
        for state_path in CURSOR_CLI_STATE_PATHS:
            if not state_path.exists():
                continue

            try:
                if state_path.is_file():
                    data = json.loads(state_path.read_text())
                    return self._cookies_from_state_data(data)
                elif state_path.is_dir():
                    # Search for state files within the directory.
                    for subfile in state_path.iterdir():
                        if subfile.suffix in (".json", "") and subfile.is_file():
                            try:
                                data = json.loads(subfile.read_text())
                                cookies = self._cookies_from_state_data(data)
                                if cookies:
                                    return cookies
                            except (json.JSONDecodeError, OSError):
                                continue
            except (json.JSONDecodeError, OSError, PermissionError) as e:
                logger.debug(f"Failed to read Cursor state at {state_path}: {e}")
                continue

        return None

    def _cookies_from_state_data(self, data: Dict[str, Any]) -> Optional[str]:
        """Extract cookie string from state data dictionary.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorCookieAuth.swift:_cookiesFromStateData()

        Args:
            data: Parsed JSON state data.

        Returns:
            Cookie string or None.
        """
        cookie_parts = []

        for cookie_name in CURSOR_COOKIE_NAMES:
            value = data.get(cookie_name)
            if value:
                cookie_parts.append(f"{cookie_name}={value}")

        if "session" in data:
            session = data["session"]
            if isinstance(session, dict):
                sid = session.get("id") or session.get("sid")
                if sid:
                    cookie_parts.append(f"cursor_session={sid}")

        if cookie_parts:
            return "; ".join(cookie_parts)

        return None

    async def _fetch_usage(self, headers: Dict[str, str]) -> Dict[str, Any]:
        """Fetch usage data from Cursor API.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorUsageAPI.swift:fetchUsage()

        Endpoint: GET /api/usage
        Auth: Cookie or Bearer token

        Args:
            headers: Authentication headers.

        Returns:
            Usage data JSON.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(CURSOR_USAGE_PATH)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)
                self._handle_response_error(response)

                if response.status_code == 401:
                    raise AuthError("Invalid Cursor authentication cookies or token")
                if response.status_code == 403:
                    raise AuthError("Cursor account lacks usage data access")

                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Cursor usage request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Cursor usage request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Cursor usage request error: {e}")

    def _parse_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse Cursor usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorUsageAPI.swift:parseUsage()

        Cursor usage tracks chat messages, code completions, and inline edits
        within a monthly billing cycle.

        Args:
            data: Usage data JSON from Cursor API.

        Returns:
            RateWindow with monthly usage percentage.
        """
        try:
            # Cursor may return usage in various formats.
            total_usage = 0
            total_limit = 0

            usage = data.get("usage", {})
            if isinstance(usage, dict):
                total_usage = usage.get("total", usage.get("used", 0))
                total_limit = usage.get("limit", usage.get("max", 0))
            elif isinstance(usage, (int, float)):
                total_usage = usage

            # Also check top-level keys.
            if total_limit == 0:
                total_limit = data.get("usage_limit", data.get("limit", 0))
            if total_usage == 0:
                total_usage = data.get("usage_used", data.get("used", 0))

            if total_limit > 0:
                used_percent = min(total_usage / total_limit, 2.0)
            else:
                used_percent = 0.0

            # Cursor usage resets at the start of each billing period (monthly).
            now = datetime.now(timezone.utc)
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=43200,  # 30 days
                resets_at=next_month,
                reset_description="Cursor monthly plan reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Cursor usage: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from Cursor data.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorProvider.swift:_parseIdentity()

        Args:
            data: Usage data JSON from Cursor API.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            user = data.get("user", {})
            if not user and "email" in data:
                user = data

            email = user.get("email")
            name = user.get("name")
            plan = data.get("plan", user.get("plan", "unknown"))

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=name,
                login_method="cookie" if self.cookies else "api_key",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Cursor identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get authentication from environment variables.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorProvider.swift:getApiKeyFromEnv()

        Checks:
        1. CURSOR_COOKIES (primary, full cookie header)
        2. CURSOR_TOKEN / CURSOR_API_KEY (fallback, bearer token)

        Returns:
            Authentication string or None.
        """
        return os.environ.get("CURSOR_COOKIES") or os.environ.get(
            "CURSOR_TOKEN"
        ) or os.environ.get("CURSOR_API_KEY")

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/Cursor/CursorProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "cursor",
            "name": "Cursor",
            "description": "Cursor AI Editor Usage",
            "linux_support": "partial",
            "auth_method": "cookie_or_bearer",
            "config_env_vars": ["CURSOR_COOKIES", "CURSOR_TOKEN", "CURSOR_API_KEY"],
            "dashboard_url": "https://cursor.com/settings/usage",
            "status_url": None,
        }
