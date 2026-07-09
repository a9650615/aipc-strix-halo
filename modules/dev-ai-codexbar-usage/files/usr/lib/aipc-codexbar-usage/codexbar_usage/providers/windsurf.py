"""Windsurf provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/Windsurf/WindsurfProvider.swift
- Sources/CodexBarCore/Providers/Windsurf/WindsurfSessionAuth.swift
- Sources/CodexBarCore/Providers/Windsurf/WindsurfUsageAPI.swift
- Sources/CodexBarCore/Providers/Windsurf/WindsurfSQLiteStore.swift

References:
- API: https://api.windsurf.com/v1/usage
- Auth: Web session token + local SQLite store
- Linux Support: partial (API works, SQLite extraction limited to Linux paths)
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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

# Windsurf API base URL.
WINDSURF_API_BASE = "https://api.windsurf.com/v1"
# Usage endpoint.
WINDSURF_USAGE_PATH = "/usage"
# Windsurf local session data paths.
WINDSURF_SESSION_PATHS = [
    Path.home() / ".config" / "windsurf" / "sessions.json",
    Path.home() / "Library" / "Application Support" / "Windsurf" / "sessions.json",
    Path.home() / "AppData" / "Local" / "Windsurf" / "sessions.json",
]
# Windsurf SQLite store paths (may contain session tokens).
WINDSURF_SQLITE_PATHS = [
    Path.home() / ".config" / "windsurf" / "state.db",
    Path.home() / "Library" / "Application Support" / "Windsurf" / "state.db",
    Path.home() / "AppData" / "Local" / "Windsurf" / "state.db",
]


class WindsurfProvider(BaseProvider):
    """Windsurf provider using session auth and usage API.

    Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfProvider.swift

    Supports:
    - Web session token authentication
    - Local SQLite state extraction for session tokens
    - Usage API at /v1/usage
    - Session and monthly rate windows

    Linux Support: partial (API works on all platforms, SQLite paths are Linux-specific)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        session_token: Optional[str] = None,
        base_url: str = WINDSURF_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Windsurf provider.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfProvider.swift:init

        Args:
            api_key: Pre-obtained bearer token.
            session_token: Windsurf web session token.
            base_url: Base URL for Windsurf API.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="windsurf",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self.session_token = session_token
        self._logger = logging.getLogger(f"providers.windsurf")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch Windsurf usage data.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfProvider.swift:fetchUsage()

        Strategy:
        1. Obtain authentication (session token, API key, or env var).
        2. Query Windsurf API for usage data.
        3. Parse usage windows and identity.

        Returns:
            UsageSnapshot with primary and secondary rate windows and identity.

        Raises:
            AuthError: If no valid authentication source found.
            NetworkError: If API request fails.
        """
        self.status = ProviderStatus.READY

        try:
            headers = await self._build_auth_headers()

            usage_data = await self._fetch_usage(headers)

            primary_window = self._parse_monthly_usage(usage_data)
            secondary_window = self._parse_session_usage(usage_data)
            identity = self._parse_identity(usage_data)

            return UsageSnapshot(
                primary=primary_window,
                secondary=secondary_window,
                identity=identity,
                updated_at=datetime.now(timezone.utc),
            )

        except ProviderError:
            raise
        except Exception as e:
            self.status = ProviderStatus.ERROR
            self.last_error = ProviderError(f"Failed to fetch Windsurf usage: {e}")
            raise self.last_error

    async def _build_auth_headers(self) -> Dict[str, str]:
        """Build authentication headers for Windsurf API.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfSessionAuth.swift:_buildAuthHeaders()

        Tries multiple auth sources in order:
        1. Explicit session_token parameter.
        2. Explicit api_key parameter.
        3. Windsurf session files.
        4. Windsurf SQLite stores.
        5. WINDSURF_TOKEN / WINDSURF_API_KEY environment variables.

        Returns:
            Headers dictionary with authentication.

        Raises:
            AuthError: If no valid authentication source.
        """
        # Check explicit session token.
        if self.session_token:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {self.session_token}"
            return headers

        # Check explicit API key.
        if self.api_key:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {self.api_key}"
            return headers

        # Try reading from session files.
        token = self._read_session_token_from_files()
        if token:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {token}"
            return headers

        # Try reading from SQLite stores.
        token = self._read_token_from_sqlite()
        if token:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {token}"
            return headers

        # Check environment variables.
        env_token = (
            os.environ.get("WINDSURF_TOKEN")
            or os.environ.get("WINDSURF_API_KEY")
            or os.environ.get("SCIPHI_API_KEY")
        )
        if env_token:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {env_token}"
            return headers

        self.status = ProviderStatus.NO_CREDENTIALS
        raise AuthError(
            "No Windsurf authentication found. Set WINDSURF_TOKEN, "
            "WINDSURF_API_KEY, or use the Windsurf editor."
        )

    def _read_session_token_from_files(self) -> Optional[str]:
        """Read Windsurf session token from local files.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfSQLiteStore.swift:_readSessionToken()

        Reads JSON session files that contain access tokens.

        Returns:
            Session token string or None.
        """
        for session_path in WINDSURF_SESSION_PATHS:
            if not session_path.exists():
                continue

            try:
                data = json.loads(session_path.read_text())

                # Handle array of sessions.
                if isinstance(data, list):
                    for item in data:
                        token = self._extract_token_from_item(item)
                        if token:
                            return token
                    continue

                if isinstance(data, dict):
                    token = self._extract_token_from_item(data)
                    if token:
                        return token

                    # Check common nested paths.
                    for key in ("tokens", "accessToken", "access_token", "session"):
                        if key in data:
                            value = data[key]
                            if isinstance(value, str) and value.startswith(("ya29.", "ey")):
                                return value
                            if isinstance(value, dict):
                                token = self._extract_token_from_item(value)
                                if token:
                                    return token

            except (json.JSONDecodeError, OSError, PermissionError) as e:
                logger.debug(f"Failed to read Windsurf session at {session_path}: {e}")
                continue

        return None

    def _extract_token_from_item(self, item: Any) -> Optional[str]:
        """Extract token from a single dictionary item.

        Args:
            item: Dictionary item to search.

        Returns:
            Token string or None.
        """
        if not isinstance(item, dict):
            return None

        for key in ("access_token", "accessToken", "token", "bearer"):
            value = item.get(key)
            if isinstance(value, str) and len(value) > 10:
                return value

        return None

    def _read_token_from_sqlite(self) -> Optional[str]:
        """Read Windsurf token from local SQLite database.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfSQLiteStore.swift:_readTokenFromSqlite()

        Windsurf stores session data in a local SQLite database.
        This searches common table/column combinations for tokens.

        Returns:
            Token string or None.
        """
        for db_path in WINDSURF_SQLITE_PATHS:
            if not db_path.exists():
                continue

            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()

                # Try common table names.
                for table in ("sessions", "tokens", "credentials", "auth", "state"):
                    try:
                        cursor.execute(
                            f"SELECT name, value FROM {table} "
                            "WHERE name IN ('access_token', 'token', 'bearer', 'session_id')"
                        )
                        rows = cursor.fetchall()

                        for col_name, col_value in rows:
                            if isinstance(col_value, str) and len(col_value) > 10:
                                conn.close()
                                return col_value

                    except sqlite3.OperationalError:
                        continue

                # Try to find any table with token-like columns.
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()

                for (table_name,) in tables:
                    try:
                        cursor.execute(f"PRAGMA table_info({table_name})")
                        columns = cursor.fetchall()
                        col_names = [c[1] for c in columns]

                        if any("token" in cn.lower() or "session" in cn.lower()
                               for cn in col_names):
                            cursor.execute(f"SELECT * FROM {table_name} LIMIT 10")
                            rows = cursor.fetchall()
                            headers = cursor.description

                            if rows and headers:
                                for row in rows:
                                    for i, value in enumerate(row):
                                        if isinstance(value, str) and len(value) > 10:
                                            conn.close()
                                            return value
                    except sqlite3.OperationalError:
                        continue

                conn.close()

            except (sqlite3.Error, OSError, PermissionError) as e:
                logger.debug(f"Failed to read Windsurf SQLite at {db_path}: {e}")
                continue

        return None

    async def _fetch_usage(self, headers: Dict[str, str]) -> Dict[str, Any]:
        """Fetch usage data from Windsurf API.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfUsageAPI.swift:fetchUsage()

        Endpoint: GET /v1/usage
        Auth: Bearer token

        Args:
            headers: Authentication headers.

        Returns:
            Usage data JSON.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(WINDSURF_USAGE_PATH)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)
                self._handle_response_error(response)

                if response.status_code == 401:
                    raise AuthError("Invalid Windsurf session token or API key")
                if response.status_code == 403:
                    raise AuthError("Windsurf account lacks usage data access")

                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Windsurf usage request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Windsurf usage request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Windsurf usage request error: {e}")

    def _parse_monthly_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse monthly usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfUsageAPI.swift:parseMonthlyUsage()

        Windsurf uses a monthly quota for AI queries and commands.

        Args:
            data: Usage data JSON from Windsurf API.

        Returns:
            RateWindow with monthly usage percentage.
        """
        try:
            # Extract monthly usage metrics.
            monthly = data.get("monthly", data.get("month", {}))
            if isinstance(monthly, dict):
                used = monthly.get("used", monthly.get("queries_used", 0))
                limit = monthly.get("limit", monthly.get("max", 0))
            else:
                used = 0
                limit = 0

            # Also check top-level keys.
            if limit == 0:
                limit = data.get("monthly_limit", data.get("limit", 0))
            if used == 0:
                used = data.get("monthly_used", data.get("used", 0))

            if limit > 0:
                used_percent = min(used / limit, 2.0)
            else:
                used_percent = 0.0

            # Monthly reset at the start of next month.
            now = datetime.now(timezone.utc)
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=43200,  # 30 days
                resets_at=next_month,
                reset_description="Windsurf monthly quota reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Windsurf monthly usage: {e}")
            return None

    def _parse_session_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse session (daily) usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfUsageAPI.swift:parseSessionUsage()

        Windsurf also tracks per-session usage for real-time feedback.

        Args:
            data: Usage data JSON from Windsurf API.

        Returns:
            RateWindow with session usage percentage.
        """
        try:
            session = data.get("session", data.get("current", {}))
            if isinstance(session, dict):
                used = session.get("used", session.get("queries_used", 0))
                limit = session.get("limit", session.get("max", 0))
            else:
                used = 0
                limit = 0

            # Also check top-level keys.
            if limit == 0:
                limit = data.get("session_limit", data.get("daily_limit", 0))
            if used == 0:
                used = data.get("session_used", data.get("daily_used", 0))

            if limit > 0:
                used_percent = min(used / limit, 2.0)
            else:
                used_percent = 0.0

            # Session window resets daily at midnight UTC.
            now = datetime.now(timezone.utc)
            tomorrow = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=1440,  # 24 hours
                resets_at=tomorrow,
                reset_description="Windsurf session resets daily",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Windsurf session usage: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from Windsurf data.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfProvider.swift:_parseIdentity()

        Args:
            data: Usage data JSON from Windsurf API.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            user = data.get("user", {})
            email = user.get("email")
            name = user.get("name")
            plan = data.get("plan", user.get("plan", "unknown"))

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=name,
                login_method="session_token" if self.session_token else "api_key",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Windsurf identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get token from environment variables.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfProvider.swift:getApiKeyFromEnv()

        Checks:
        1. WINDSURF_TOKEN (primary)
        2. WINDSURF_API_KEY (fallback)
        3. SCIPHI_API_KEY (legacy, Windsurf was formerly Sciphi)

        Returns:
            Token string or None.
        """
        return (
            os.environ.get("WINDSURF_TOKEN")
            or os.environ.get("WINDSURF_API_KEY")
            or os.environ.get("SCIPHI_API_KEY")
        )

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/Windsurf/WindsurfProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "windsurf",
            "name": "Windsurf",
            "description": "Windsurf AI Editor Usage",
            "linux_support": "partial",
            "auth_method": "session_token",
            "config_env_vars": ["WINDSURF_TOKEN", "WINDSURF_API_KEY", "SCIPHI_API_KEY"],
            "dashboard_url": "https://windsurf.com/settings/usage",
            "status_url": None,
        }
