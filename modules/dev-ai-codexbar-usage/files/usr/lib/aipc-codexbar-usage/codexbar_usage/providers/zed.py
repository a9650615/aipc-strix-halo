"""Zed provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/Zed/ZedProvider.swift
- Sources/CodexBarCore/Providers/Zed/ZedKeychainAuth.swift
- Sources/CodexBarCore/Providers/Zed/ZedCloudAPI.swift

References:
- API: https://cloud.zed.dev/client/users/me
- Auth: macOS Keychain session token
- Linux Support: not-supported (requires macOS Keychain for session token extraction)
"""

import json
import logging
import os
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

# Zed Cloud API base URL.
ZED_API_BASE = "https://cloud.zed.dev"
# User info endpoint.
ZED_USER_PATH = "/client/users/me"
# Usage endpoint.
ZED_USAGE_PATH = "/client/usage"
# Zed auth token file (non-macOS fallback).
ZED_TOKEN_FILE_PATHS = [
    Path.home() / ".local" / "share" / "zed" / "auth_token",
    Path.home() / ".config" / "zed" / "auth_token",
    Path.home() / ".zed" / "auth_token",
]
# Zed keychain / auth store paths (macOS specific).
ZED_MACOS_AUTH_PATHS = [
    Path.home() / "Library" / "Application Support" / "zed" / "auth_token",
    Path.home() / "Library" / "Application Support" / "Zed" / "auth_token",
]


class ZedProvider(BaseProvider):
    """Zed provider using Cloud API and keychain auth.

    Ported from: Sources/CodexBarCore/Providers/Zed/ZedProvider.swift

    Supports:
    - Zed Cloud user info endpoint (/client/users/me)
    - Usage tracking endpoint (/client/usage)
    - macOS Keychain session authentication
    - Fallback to auth token file on non-macOS platforms

    Linux Support: not-supported (session token requires macOS Keychain access)
    Note: API calls work on any platform if a valid token is provided directly.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        session_token: Optional[str] = None,
        base_url: str = ZED_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Zed provider.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedProvider.swift:init

        Args:
            api_key: Pre-obtained bearer token.
            session_token: Zed Cloud session token.
            base_url: Base URL for Zed Cloud API.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="zed",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self.session_token = session_token
        self._logger = logging.getLogger(f"providers.zed")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch Zed Cloud usage data.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedProvider.swift:fetchUsage()

        Strategy:
        1. Obtain authentication (session token, API key, or token file).
        2. Query Zed Cloud API for usage data.
        3. Parse usage windows and identity.

        Returns:
            UsageSnapshot with primary rate window and identity.

        Raises:
            AuthError: If no valid authentication source found.
            NetworkError: If API request fails.
            ProviderError: If platform is not supported.
        """
        self.status = ProviderStatus.READY

        try:
            # Check if we are on macOS (required for full keychain support).
            if not self._is_macos_and_has_keychain():
                # Still allow API access if token is provided directly.
                if not self.session_token and not self.api_key:
                    self._logger.info(
                        "Zed provider: Keychain auth not available on non-macOS; "
                        "providing token via config or WIZARD_TOKEN env var is required."
                    )

            headers = await self._build_auth_headers()

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
            self.last_error = ProviderError(f"Failed to fetch Zed usage: {e}")
            raise self.last_error

    def _is_macos_and_has_keychain(self) -> bool:
        """Check if running on macOS with Keychain access.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedKeychainAuth.swift:_isMacOS()

        Returns:
            True if running on macOS (Darwin).
        """
        import platform
        return platform.system() == "Darwin"

    async def _build_auth_headers(self) -> Dict[str, str]:
        """Build authentication headers for Zed Cloud API.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedKeychainAuth.swift:_buildAuthHeaders()

        Tries multiple auth sources in order:
        1. Explicit session_token parameter.
        2. Explicit api_key parameter.
        3. Auth token files.
        4. ZED_TOKEN / ZED_API_KEY environment variables.

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

        # Try reading from token files.
        token = self._read_token_from_files()
        if token:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {token}"
            return headers

        # Check environment variables.
        env_token = (
            os.environ.get("ZED_TOKEN")
            or os.environ.get("ZED_API_KEY")
            or os.environ.get("WIZARD_TOKEN")
        )
        if env_token:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {env_token}"
            return headers

        self.status = ProviderStatus.NO_CREDENTIALS
        raise AuthError(
            "No Zed authentication found. Set ZED_TOKEN, ZED_API_KEY, "
            "or use the Zed editor on macOS for Keychain-based auth."
        )

    def _read_token_from_files(self) -> Optional[str]:
        """Read Zed auth token from local files.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedKeychainAuth.swift:_readTokenFromFile()

        Searches for auth tokens in common Zed configuration paths.
        On macOS, also checks the Keychain (via subprocess to security CLI).

        Returns:
            Token string or None.
        """
        # Search file-based token paths first.
        for token_path in ZED_TOKEN_FILE_PATHS + ZED_MACOS_AUTH_PATHS:
            if not token_path.exists():
                continue

            try:
                token = token_path.read_text().strip()
                if token and len(token) > 10:
                    return token
            except (OSError, PermissionError) as e:
                logger.debug(f"Failed to read token at {token_path}: {e}")
                continue

        # On macOS, try reading from Keychain via `security` CLI.
        if self._is_macos_and_has_keychain():
            token = self._read_from_keychain()
            if token:
                return token

        return None

    def _read_from_keychain(self) -> Optional[str]:
        """Read Zed token from macOS Keychain.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedKeychainAuth.swift:_readFromKeychain()

        Uses the `security` command-line tool to query the Keychain for
        the Zed session token.

        Returns:
            Token string or None.
        """
        try:
            import subprocess
            result = subprocess.run(
                [
                    "security", "find-generic-password",
                    "-s", "zed",
                    "-w",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.debug(f"Failed to read Zed from Keychain: {e}")

        return None

    async def _fetch_usage(self, headers: Dict[str, str]) -> Dict[str, Any]:
        """Fetch usage data from Zed Cloud API.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedCloudAPI.swift:fetchUsage()

        Endpoint: GET /client/usage
        Auth: Bearer token

        Args:
            headers: Authentication headers.

        Returns:
            Usage data JSON.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(ZED_USAGE_PATH)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)
                self._handle_response_error(response)

                if response.status_code == 401:
                    raise AuthError("Invalid Zed Cloud session token")
                if response.status_code == 403:
                    raise AuthError("Zed Cloud account lacks usage data access")

                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Zed usage request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Zed usage request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Zed usage request error: {e}")

    def _parse_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse Zed usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedCloudAPI.swift:parseUsage()

        Zed Cloud tracks AI assistant usage within a monthly billing cycle.

        Args:
            data: Usage data JSON from Zed Cloud API.

        Returns:
            RateWindow with monthly usage percentage.
        """
        try:
            # Extract usage metrics.
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

            # Zed usage resets at the start of each billing period (monthly).
            now = datetime.now(timezone.utc)
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=43200,  # 30 days
                resets_at=next_month,
                reset_description="Zed Cloud monthly plan reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Zed usage: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from Zed data.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedProvider.swift:_parseIdentity()

        Args:
            data: Usage data JSON from Zed Cloud API.

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
            logger.warning(f"Failed to parse Zed identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get token from environment variables.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedProvider.swift:getApiKeyFromEnv()

        Checks:
        1. ZED_TOKEN (primary)
        2. ZED_API_KEY (fallback)
        3. WIZARD_TOKEN (legacy, for Zed's internal auth)

        Returns:
            Token string or None.
        """
        return (
            os.environ.get("ZED_TOKEN")
            or os.environ.get("ZED_API_KEY")
            or os.environ.get("WIZARD_TOKEN")
        )

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/Zed/ZedProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "zed",
            "name": "Zed",
            "description": "Zed Cloud AI Usage",
            "linux_support": "not-supported",
            "auth_method": "session_token",
            "config_env_vars": ["ZED_TOKEN", "ZED_API_KEY", "WIZARD_TOKEN"],
            "dashboard_url": "https://cloud.zed.dev/settings/usage",
            "status_url": None,
        }
