"""Gemini provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/Gemini/GeminiProvider.swift
- Sources/CodexBarCore/Providers/Gemini/GeminiOAuth.swift
- Sources/CodexBarCore/Providers/Gemini/GeminiUsageReport.swift

References:
- API Endpoints: Sources/CodexBarCore/Providers/Gemini/GeminiProvider.swift
- Auth: Bearer token from Gemini CLI credentials
- Linux Support: full
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

# Google OAuth token endpoint for Gemini CLI credentials.
GEMINI_AUTH_URL = "https://oauth2.googleapis.com/token"
# Gemini content API base URL for usage queries.
GEMINI_API_BASE = "https://content-aio.googleapis.com/v1"
# Gemini CLI credential file locations.
GEMINI_CLI_CREDENTIALS_PATHS = [
    Path.home() / ".config" / "gemini" / "credentials.json",
    Path.home() / ".gemini" / "credentials.json",
]


class GeminiProvider(BaseProvider):
    """Gemini provider using OAuth and content API.

    Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiProvider.swift

    Supports:
    - OAuth Bearer token authentication
    - Token retrieval from Gemini CLI credential files
    - Usage report via content API models endpoint

    Linux Support: full
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        token_file: Optional[Path] = None,
        base_url: str = GEMINI_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Gemini provider.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiProvider.swift:init

        Args:
            api_key: Pre-obtained OAuth access token.
            token_file: Path to file containing the OAuth access token.
            base_url: Base URL for content API endpoints.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="gemini",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self.token_file = token_file
        self._logger = logging.getLogger(f"providers.gemini")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch Gemini usage.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiProvider.swift:fetchUsage()

        Steps:
        1. Obtain or refresh OAuth access token.
        2. Query content API for usage metrics.

        Returns:
            UsageSnapshot with primary rate window and identity.

        Raises:
            AuthError: If token cannot be obtained.
            NetworkError: If API request fails.
        """
        self.status = ProviderStatus.READY

        try:
            # Ensure we have a valid access token.
            token = await self._get_valid_token()

            # Build authenticated headers with the token.
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {token}"

            # Fetch usage from content API.
            usage_data = await self._fetch_usage_report(headers)

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
            self.last_error = ProviderError(f"Failed to fetch Gemini usage: {e}")
            raise self.last_error

    async def _get_valid_token(self) -> str:
        """Obtain a valid OAuth access token.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiOAuth.swift:_getValidToken()

        Tries:
        1. api_key (pre-obtained token).
        2. Token from config file.
        3. Token from Gemini CLI credential files.
        4. Token from environment variable GEMINI_API_KEY.

        Returns:
            Valid access token string.

        Raises:
            AuthError: If no token source is available.
        """
        # Check pre-obtained token first.
        if self.api_key:
            return self.api_key

        # Check config token file.
        if self.token_file and self.token_file.exists():
            token = self.token_file.read_text().strip()
            if token:
                return token

        # Check Gemini CLI credential files.
        for cred_path in GEMINI_CLI_CREDENTIALS_PATHS:
            if cred_path.exists():
                try:
                    creds = json.loads(cred_path.read_text())
                    access_token = creds.get("access_token", "")
                    if access_token:
                        return access_token
                except (json.JSONDecodeError, OSError) as e:
                    logger.debug(f"Failed to read Gemini credentials at {cred_path}: {e}")
                    continue

        # Check environment variable.
        env_token = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if env_token:
            return env_token

        self.status = ProviderStatus.NO_CREDENTIALS
        raise AuthError(
            "No Gemini access token found. "
            "Set GEMINI_API_KEY, configure Gemini CLI, "
            "or provide a token file."
        )

    async def _refresh_token_if_needed(self, token: str) -> str:
        """Refresh OAuth token if expired.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiOAuth.swift:_refreshTokenIfNeeded()

        Uses the refresh_token from credential files to obtain a new access_token.

        Args:
            token: Current access token (may be expired).

        Returns:
            Valid access token string.
        """
        # If no refresh token source is available, return the existing token.
        # The caller will get a 401 and can retry after manual re-authentication.
        refresh_source = self._find_refresh_token()
        if not refresh_source:
            return token

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    GEMINI_AUTH_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_source,
                        "client_id": os.environ.get(
                            "GEMINI_CLIENT_ID",
                            "771352970391-9si4o2t4bdr515jd2fh2sbu3h0k7k7tl.apps.googleusercontent.com"
                        ),
                        "client_secret": os.environ.get("GEMINI_CLIENT_SECRET", ""),
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code == 200:
                    data = response.json()
                    return data.get("access_token", token)

                logger.warning(f"Token refresh failed with status {response.status_code}")

            except (httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(f"Token refresh network error: {e}")

        return token

    def _find_refresh_token(self) -> Optional[str]:
        """Find a refresh token from credential files.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiOAuth.swift:_findRefreshToken()

        Returns:
            Refresh token string or None.
        """
        for cred_path in GEMINI_CLI_CREDENTIALS_PATHS:
            if cred_path.exists():
                try:
                    creds = json.loads(cred_path.read_text())
                    refresh_token = creds.get("refresh_token")
                    if refresh_token:
                        return refresh_token
                except (json.JSONDecodeError, OSError):
                    continue
        return None

    async def _fetch_usage_report(
        self, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch usage report from content API.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiUsageReport.swift

        Endpoint: GET /v1/models (with usage metadata)
        Auth: Bearer token

        Args:
            headers: Request headers with Authorization.

        Returns:
            Usage report JSON data.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint("/v1/models")

        try:
            response = await httpx.AsyncClient().get(
                url, headers=headers, timeout=30.0
            )
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid Gemini OAuth token")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Usage report request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Usage report request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Usage report request error: {e}")

    def _parse_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiUsageReport.swift:parseUsage()

        Args:
            data: Usage report JSON data.

        Returns:
            RateWindow with usage percentage.
        """
        try:
            # Extract usage metrics from Gemini API response.
            total_usage = data.get("total_usage", 0)
            total_limit = data.get("total_limit", 0)

            if total_limit > 0:
                used_percent = min(total_usage / total_limit, 2.0)
            else:
                used_percent = 0.0

            # Estimate reset time based on quota period.
            resets_at = datetime.now(timezone.utc) + timedelta(days=30)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=43200,  # 30 days in minutes
                resets_at=resets_at,
                reset_description="Monthly quota reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Gemini usage: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity information from API response.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiProvider.swift:_parseIdentity()

        Args:
            data: API response JSON data.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            # Extract user info from token or response.
            user_info = data.get("user", {})
            email = user_info.get("email") or data.get("email")

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=None,
                login_method="oauth_google",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Gemini identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get token from environment variables.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiProvider.swift:getApiKeyFromEnv()

        Checks:
        1. GEMINI_API_KEY (primary)
        2. GOOGLE_API_KEY (fallback)

        Returns:
            API key / access token string or None.
        """
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/Gemini/GeminiProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "gemini",
            "name": "Gemini",
            "description": "Google Gemini Usage (Content API)",
            "linux_support": "full",
            "auth_method": "oauth_bearer",
            "config_env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "dashboard_url": "https://aistudio.google.com/usage",
            "status_url": "https://status.cloud.google.com",
        }
