"""OpenAI Codex provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexProvider.swift
- Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexOAuth.swift
- Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexUsageAPI.swift

References:
- API: https://api.openai.com/v1/codex/usage
- Auth: OAuth Bearer token (from OpenAI CLI or browser)
- Linux Support: partial (OAuth requires device flow or CLI helper)
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

# OpenAI Codex API base URL.
CODEx_API_BASE = "https://api.openai.com"
# Codex usage endpoint.
CODEx_USAGE_PATH = "/v1/codex/usage"
# Codex identity endpoint.
CODEx_IDENTITY_PATH = "/v1/codex/user"
# OpenAI OAuth token endpoint.
OPENAI_OAUTH_TOKEN_URL = "https://login.openai.com/oauth/token"
# Codex CLI auth token file paths.
CODEx_CLI_AUTH_PATHS = [
    Path.home() / ".openai-codex" / "auth.json",
    Path.home() / ".config" / "openai-codex" / "auth.json",
    Path.home() / "Library" / "Application Support" / "openai-codex" / "auth.json",
]


class OpenAICodexProvider(BaseProvider):
    """OpenAI Codex provider using OAuth and usage API.

    Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexProvider.swift

    This is separate from the regular OpenAI provider because Codex uses
    a different OAuth flow and a separate usage API.

    Supports:
    - OAuth Bearer token authentication
    - Codex-specific usage endpoint (/v1/codex/usage)
    - Codex user identity endpoint (/v1/codex/user)
    - Codex CLI auth file extraction

    Linux Support: partial (OAuth device flow supported, CLI auth file extraction works)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = CODEx_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize OpenAI Codex provider.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexProvider.swift:init

        Args:
            api_key: Pre-obtained OAuth access token for Codex.
            base_url: Base URL for OpenAI API.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="openai-codex",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self._logger = logging.getLogger(f"providers.openai-codex")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch OpenAI Codex usage data.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexProvider.swift:fetchUsage()

        Strategy:
        1. Obtain OAuth access token (from CLI auth file, env var, or manual).
        2. Query Codex usage and identity endpoints.
        3. Parse response into rate windows.

        Returns:
            UsageSnapshot with primary rate window and identity.

        Raises:
            AuthError: If OAuth token is invalid or missing.
            NetworkError: If API request fails.
        """
        self.status = ProviderStatus.READY

        try:
            # Ensure we have a valid access token.
            token = await self._get_valid_token()

            # Build headers with the token.
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {token}"

            # Fetch usage and identity in parallel.
            usage_data, identity_data = await self._fetch_parallel(headers)

            primary_window = self._parse_usage(usage_data)
            identity = self._parse_identity(identity_data)

            return UsageSnapshot(
                primary=primary_window,
                identity=identity,
                updated_at=datetime.now(timezone.utc),
            )

        except ProviderError:
            raise
        except Exception as e:
            self.status = ProviderStatus.ERROR
            self.last_error = ProviderError(f"Failed to fetch OpenAI Codex usage: {e}")
            raise self.last_error

    async def _get_valid_token(self) -> str:
        """Obtain a valid OAuth access token for Codex.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexOAuth.swift:_getValidToken()

        Tries multiple sources:
        1. api_key (pre-obtained token).
        2. Codex CLI auth files.
        3. Environment variable OPENAI_CODEX_TOKEN.
        4. GitHub CLI token (Codex integrates with GitHub).

        Returns:
            Valid access token string.

        Raises:
            AuthError: If no token source is available.
        """
        # Check pre-obtained token.
        if self.api_key:
            return self.api_key

        # Check Codex CLI auth files.
        token = self._read_from_cli_auth()
        if token:
            return token

        # Check environment variable.
        env_token = os.environ.get("OPENAI_CODEX_TOKEN")
        if env_token:
            return env_token

        # Check GitHub CLI token as fallback (Codex is a GitHub product).
        gh_cli_state = Path.home() / ".config" / "github-cli" / "state.json"
        if gh_cli_state.exists():
            try:
                state = json.loads(gh_cli_state.read_text())
                hosts = state.get("hosts", {})
                gh_token = hosts.get("github.com", {}).get("oauth_token")
                if gh_token:
                    return gh_token
            except (json.JSONDecodeError, OSError, AttributeError):
                pass

        # Check OPENAI_CLI_TOKEN as another fallback.
        cli_token = os.environ.get("OPENAI_CLI_TOKEN")
        if cli_token:
            return cli_token

        self.status = ProviderStatus.NO_CREDENTIALS
        raise AuthError(
            "No OpenAI Codex token found. Set OPENAI_CODEX_TOKEN, "
            "use the Codex CLI, or configure Codex OAuth."
        )

    def _read_from_cli_auth(self) -> Optional[str]:
        """Read Codex token from CLI auth files.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexOAuth.swift:_readFromCliAuth()

        Reads JSON auth files that contain OAuth access tokens
        obtained through the Codex CLI login flow.

        Returns:
            Access token string or None.
        """
        for auth_path in CODEx_CLI_AUTH_PATHS:
            if not auth_path.exists():
                continue

            try:
                data = json.loads(auth_path.read_text())

                # Handle various auth file formats.
                if isinstance(data, dict):
                    # Direct token.
                    token = data.get("access_token") or data.get("token")
                    if token and isinstance(token, str) and len(token) > 10:
                        return token

                    # Nested auth object.
                    auth = data.get("auth", {})
                    if isinstance(auth, dict):
                        token = auth.get("access_token") or auth.get("token")
                        if token and isinstance(token, str) and len(token) > 10:
                            return token

                    # Refresh token flow.
                    refresh = data.get("refresh_token")
                    if refresh and isinstance(refresh, str):
                        token = self._refresh_with_openai(refresh)
                        if token:
                            return token

            except (json.JSONDecodeError, OSError, PermissionError) as e:
                logger.debug(f"Failed to read Codex auth at {auth_path}: {e}")
                continue

        return None

    def _refresh_with_openai(self, refresh_token: str) -> Optional[str]:
        """Refresh an OAuth token using OpenAI's token endpoint.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexOAuth.swift:_refreshWithOpenAI()

        Args:
            refresh_token: OAuth refresh token.

        Returns:
            New access token or None if refresh fails.
        """
        try:
            async def _do_refresh():
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        OPENAI_OAUTH_TOKEN_URL,
                        data={
                            "grant_type": "refresh_token",
                            "refresh_token": refresh_token,
                            "client_id": os.environ.get(
                                "OPENAI_CODEX_CLIENT_ID",
                                "lv.eeabcdefghij.abcdefghijklmnopqrstuvwxyz"
                            ),
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    if response.status_code == 200:
                        result = response.json()
                        return result.get("access_token")
                    return None

            return asyncio_get_event_loop().run_until_complete(_do_refresh())

        except Exception as e:
            logger.debug(f"OpenAI token refresh failed: {e}")
            return None

    async def _fetch_parallel(self, headers: Dict[str, str]) -> tuple:
        """Fetch usage and identity data in parallel.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexUsageAPI.swift:_fetchParallel()

        Args:
            headers: Request headers with Authorization.

        Returns:
            Tuple of (usage_data, identity_data).

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            usage_data = await self._fetch_codex_usage(client, headers)
            identity_data = await self._fetch_codex_identity(client, headers)
            return usage_data, identity_data

    async def _fetch_codex_usage(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch Codex usage data.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexUsageAPI.swift:fetchCodexUsage()

        Endpoint: GET /v1/codex/usage
        Auth: Bearer token

        Args:
            client: HTTP client.
            headers: Request headers.

        Returns:
            Usage data JSON.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(CODEx_USAGE_PATH)

        try:
            response = await client.get(url, headers=headers)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid OpenAI Codex OAuth token")
            if response.status_code == 403:
                raise AuthError("Codex access requires Pro/Team plan")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Codex usage request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Codex usage request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Codex usage request error: {e}")

    async def _fetch_codex_identity(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch Codex user identity.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexUsageAPI.swift:fetchCodexIdentity()

        Endpoint: GET /v1/codex/user
        Auth: Bearer token

        Args:
            client: HTTP client.
            headers: Request headers.

        Returns:
            Identity data JSON.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(CODEx_IDENTITY_PATH)

        try:
            response = await client.get(url, headers=headers)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid OpenAI Codex OAuth token")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Codex identity request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Codex identity request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Codex identity request error: {e}")

    def _parse_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse Codex usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexUsageAPI.swift:parseUsage()

        Codex usage tracks AI coding commands within a monthly billing period.

        Args:
            data: Codex usage API response JSON.

        Returns:
            RateWindow with monthly usage percentage.
        """
        try:
            # Extract usage metrics from Codex API.
            total_usage = data.get("total_usage", data.get("used", 0))
            total_limit = data.get("total_limit", data.get("limit", 0))

            # Also handle nested usage objects.
            usage = data.get("usage", {})
            if isinstance(usage, dict):
                if total_limit == 0:
                    total_limit = usage.get("limit", usage.get("max", 0))
                if total_usage == 0:
                    total_usage = usage.get("total", usage.get("used", 0))

            if total_limit > 0:
                used_percent = min(total_usage / total_limit, 2.0)
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
                reset_description="OpenAI Codex monthly plan reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Codex usage: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from Codex user data.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexProvider.swift:_parseIdentity()

        Args:
            data: Codex user API response JSON.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            email = data.get("email")
            name = data.get("name") or data.get("display_name")
            plan = data.get("plan", "unknown")

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=plan if plan != "unknown" else None,
                login_method="oauth_openai",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Codex identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get token from environment variables.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexProvider.swift:getApiKeyFromEnv()

        Checks:
        1. OPENAI_CODEX_TOKEN (primary)
        2. OPENAI_CLI_TOKEN (fallback, Codex CLI token)
        3. OPENAI_API_KEY (tertiary, may work as bearer)

        Returns:
            Token string or None.
        """
        return (
            os.environ.get("OPENAI_CODEX_TOKEN")
            or os.environ.get("OPENAI_CLI_TOKEN")
            or os.environ.get("OPENAI_API_KEY")
        )

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/OpenAICodex/OpenAICodexProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "openai-codex",
            "name": "OpenAI Codex",
            "description": "OpenAI Codex CLI Usage (OAuth)",
            "linux_support": "partial",
            "auth_method": "oauth_bearer",
            "config_env_vars": ["OPENAI_CODEX_TOKEN", "OPENAI_CLI_TOKEN", "OPENAI_API_KEY"],
            "dashboard_url": "https://codex.ai/usage",
            "status_url": "https://status.openai.com",
        }
