"""Claude provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/Claude/ClaudeProvider.swift
- Sources/CodexBarCore/Providers/Claude/ClaudeAdminAPI.swift
- Sources/CodexBarCore/Providers/Claude/ClaudeUsageReport.swift

References:
- API Endpoints: Sources/CodexBarCore/Providers/Claude/ClaudeAdminAPI.swift
- Auth: x-api-key: sk-ant-admin-...
- Linux Support: full
"""

import logging
import os
from datetime import datetime, timedelta, timezone
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

# Anthropic Admin API endpoints.
ADMIN_API_BASE = "https://api.anthropic.com/v1"
# Session usage window constants.
SESSION_USAGE_MINUTES = 300  # 5 hours in minutes
WEEKLY_USAGE_MINUTES = 10080  # 7 days in minutes


class ClaudeProvider(BaseProvider):
    """Claude provider using Admin API and session usage tracking.

    Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeProvider.swift

    Supports:
    - Admin API key authentication (sk-ant-admin-...)
    - Session usage window (5 hours)
    - Weekly usage window (7 days)
    - Account identity and plan info

    Linux Support: full
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = ADMIN_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Claude provider.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeProvider.swift:init

        Args:
            api_key: Claude Admin API key (sk-ant-admin-...)
            base_url: Base URL for Admin API endpoints
            config: Additional configuration
        """
        super().__init__(
            provider_id="claude",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self._logger = logging.getLogger(f"providers.claude")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch Claude organization usage.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeProvider.swift:fetchUsage()

        Makes two parallel requests:
        1. Account info (identity + plan)
        2. Usage report (message counts and costs)

        Returns:
            UsageSnapshot with primary (session) and secondary (weekly) rate windows
            and identity information.

        Raises:
            AuthError: If API key is invalid
            NetworkError: If request fails
        """
        self.status = ProviderStatus.READY

        try:
            account_info, usage_data = await self._fetch_parallel()

            session_window = self._parse_session_usage(usage_data)
            weekly_window = self._parse_weekly_usage(usage_data)
            identity = self._parse_identity(account_info)

            return UsageSnapshot(
                primary=session_window,
                secondary=weekly_window,
                identity=identity,
                updated_at=datetime.now(timezone.utc),
            )

        except ProviderError:
            raise
        except Exception as e:
            self.status = ProviderStatus.ERROR
            self.last_error = ProviderError(f"Failed to fetch Claude usage: {e}")
            raise self.last_error

    async def _fetch_parallel(self) -> tuple:
        """Fetch account info and usage report in parallel.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeAdminAPI.swift:_fetchParallel()

        Returns:
            Tuple of (account_info, usage_data).

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = self._create_auth_headers()

            # Fetch account info from /v1/account endpoint.
            account_info = await self._fetch_account_info(client, headers)

            # Fetch usage from /v1/messages endpoint with usage tracking.
            usage_data = await self._fetch_usage_report(client, headers)

            return account_info, usage_data

    async def _fetch_account_info(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch account info from Admin API.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeAdminAPI.swift:fetchAccountInfo()

        Endpoint: GET /v1/account
        Auth: x-api-key: sk-ant-admin-...

        Args:
            client: HTTP client.
            headers: Request headers.

        Returns:
            Account info JSON data.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint("/v1/account")

        try:
            response = await client.get(url, headers=headers)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid Claude Admin API key")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Account info request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Account info request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Account info request error: {e}")

    async def _fetch_usage_report(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch usage report from messages endpoint.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeUsageReport.swift

        Endpoint: GET /v1/messages (with usage tracking query params)
        Auth: x-api-key: sk-ant-admin-...

        Args:
            client: HTTP client.
            headers: Request headers.

        Returns:
            Usage report JSON data.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint("/v1/messages")
        params = {
            "include_usage": "true",
            "period": "current",
        }

        try:
            response = await client.get(url, headers=headers, params=params)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid Claude Admin API key")

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

    def _parse_session_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse session (5-hour) usage window.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeUsageReport.swift:parseSessionUsage()

        The session window tracks API calls within a 5-hour rolling window.

        Args:
            data: Usage report JSON data.

        Returns:
            RateWindow with session usage percentage.
        """
        try:
            # Extract session-level usage metrics.
            session_used = data.get("session_usage", 0)
            session_limit = data.get("session_limit", 0)

            if session_limit > 0:
                used_percent = min(session_used / session_limit, 2.0)
            else:
                used_percent = 0.0

            # Session window resets after 5 hours from first request.
            resets_at = datetime.now(timezone.utc) + timedelta(minutes=SESSION_USAGE_MINUTES)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=SESSION_USAGE_MINUTES,
                resets_at=resets_at,
                reset_description=f"Session usage resets in {SESSION_USAGE_MINUTES} minutes",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Claude session usage: {e}")
            return None

    def _parse_weekly_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse weekly (7-day) usage window.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeUsageReport.swift:parseWeeklyUsage()

        The weekly window tracks API costs over a 7-day period.

        Args:
            data: Usage report JSON data.

        Returns:
            RateWindow with weekly usage percentage.
        """
        try:
            # Extract weekly cost and budget.
            weekly_cost = data.get("weekly_cost", 0)
            weekly_budget = data.get("weekly_budget", 0)

            if weekly_budget > 0:
                used_percent = min(weekly_cost / weekly_budget, 2.0)
            else:
                used_percent = 0.0

            # Weekly window resets 7 days from now.
            resets_at = datetime.now(timezone.utc) + timedelta(minutes=WEEKLY_USAGE_MINUTES)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=WEEKLY_USAGE_MINUTES,
                resets_at=resets_at,
                reset_description=f"Weekly budget resets in {WEEKLY_USAGE_MINUTES // 60} hours",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Claude weekly usage: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity information from account data.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeAdminAPI.swift:_parseIdentity()

        Args:
            data: Account info JSON data.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            email = data.get("email")
            plan = data.get("plan", "unknown")
            org_name = data.get("organization", {}).get("name")

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=org_name,
                login_method="admin_api_key",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Claude identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get API key from environment variables.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeProvider.swift:getApiKeyFromEnv()

        Checks:
        1. ANTHROPIC_ADMIN_KEY (primary, sk-ant-admin-...)
        2. ANTHROPIC_API_KEY (fallback)

        Returns:
            API key string or None.
        """
        return (
            os.environ.get("ANTHROPIC_ADMIN_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/Claude/ClaudeProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "claude",
            "name": "Claude",
            "description": "Anthropic Claude Usage (Admin API)",
            "linux_support": "full",
            "auth_method": "api_key",
            "config_env_vars": ["ANTHROPIC_ADMIN_KEY", "ANTHROPIC_API_KEY"],
            "dashboard_url": "https://console.anthropic.com/settings/keys",
            "status_url": "https://status.anthropic.com",
        }
