"""OpenAI provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/OpenAI/OpenAIProvider.swift
- Sources/CodexBarCore/Providers/OpenAI/OpenAICostReport.swift
- Sources/CodexBarCore/Providers/OpenAI/OpenAIUsageReport.swift

References:
- API Endpoints: Openspec/changes/codexbar-usage-integration/docs/architecture-analysis.md#10-1
- Auth: Authorization: Bearer sk-ant-admin-...
- Linux Support: full
"""

import logging
import os
from datetime import datetime, timedelta, timezone
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


class OpenAIProvider(BaseProvider):
    """OpenAI provider using Admin API.

    Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAIProvider.swift

    Supports:
    - Organization cost reports
    - Organization usage reports (message counts)
    - Admin API key authentication

    Linux Support: full
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        organization_id: Optional[str] = None,
        base_url: str = "https://api.openai.com",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize OpenAI provider.

        Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAIProvider.swift:init

        Args:
            api_key: OpenAI Admin API key (sk-ant-admin-...)
            organization_id: Organization ID (optional)
            base_url: Base URL for API endpoints
            start_date: Start date for cost report (defaults to 30 days ago)
            end_date: End date for cost report (defaults to now)
            config: Additional configuration
        """
        super().__init__(
            provider_id="openai",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self.organization_id = organization_id
        self.start_date = start_date or (datetime.now(timezone.utc) - timedelta(days=30))
        self.end_date = end_date or datetime.now(timezone.utc)
        self._logger = logging.getLogger(f"providers.openai")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch OpenAI organization usage.

        Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAIProvider.swift:fetchUsage()

        Makes two parallel requests:
        1. Organization cost report
        2. Organization usage report (message counts)

        Returns:
            UsageSnapshot with rate windows and identity information

        Raises:
            AuthError: If API key is invalid
            NetworkError: If request fails
        """
        self.status = ProviderStatus.READY

        try:
            # Fetch cost report and usage report in parallel
            cost_data, usage_data = await self._fetch_parallel()

            # Parse results
            primary_window = self._parse_cost_report(cost_data)
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
            self.last_error = ProviderError(f"Failed to fetch OpenAI usage: {e}")
            raise self.last_error

    async def _fetch_parallel(self) -> tuple:
        """Fetch cost report and usage report in parallel.

        Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAIProvider.swift:_fetchParallel()

        Returns:
            Tuple of (cost_data, usage_data)

        Raises:
            NetworkError: If requests fail
            AuthError: If authentication fails
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = self._create_auth_headers()

            # Fetch cost report
            cost_data = await self._fetch_cost_report(client, headers)

            # Fetch usage report
            usage_data = await self._fetch_usage_report(client, headers)

            return cost_data, usage_data

    async def _fetch_cost_report(self, client: httpx.AsyncClient, headers: Dict[str, str]) -> Dict[str, Any]:
        """Fetch organization cost report.

        Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAICostReport.swift

        Endpoint: GET /v1/organization/cost_report
        Auth: Authorization: Bearer <admin_key>

        Args:
            client: HTTP client
            headers: Request headers

        Returns:
            Cost report data

        Raises:
            NetworkError: On request failure
            AuthError: On authentication failure
        """
        endpoint = "/v1/organization/cost_report"
        params = {
            "starting_at": int(self.start_date.timestamp()),
            "ending_at": int(self.end_date.timestamp()),
            "bucket_width": "1d",
        }

        if self.organization_id:
            endpoint = f"/v1/organization/{self.organization_id}/cost_report"

        url = self._validate_endpoint(endpoint)

        try:
            response = await client.get(url, headers=headers, params=params)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid OpenAI Admin API key")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(f"Cost report request failed: {e}", e.response.status_code)
        except httpx.TimeoutException:
            raise NetworkError("Cost report request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Cost report request error: {e}")

    async def _fetch_usage_report(self, client: httpx.AsyncClient, headers: Dict[str, str]) -> Dict[str, Any]:
        """Fetch organization usage report (message counts).

        Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAIUsageReport.swift

        Endpoint: GET /v1/organization/usage_report/messages
        Auth: Authorization: Bearer <admin_key>

        Args:
            client: HTTP client
            headers: Request headers

        Returns:
            Usage report data

        Raises:
            NetworkError: On request failure
            AuthError: On authentication failure
        """
        endpoint = "/v1/organization/usage_report/messages"

        if self.organization_id:
            endpoint = f"/v1/organization/{self.organization_id}/usage_report/messages"

        url = self._validate_endpoint(endpoint)
        params = {
            "starting_at": int(self.start_date.timestamp()),
            "ending_at": int(self.end_date.timestamp()),
            "group_by": "model",
        }

        try:
            response = await client.get(url, headers=headers, params=params)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid OpenAI Admin API key")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(f"Usage report request failed: {e}", e.response.status_code)
        except httpx.TimeoutException:
            raise NetworkError("Usage report request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Usage report request error: {e}")

    def _parse_cost_report(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse cost report data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAICostReport.swift:parseCostReport()

        Args:
            data: Cost report JSON data

        Returns:
            RateWindow with usage percentage
        """
        try:
            # Extract total cost and budget
            total_cost = data.get("total_cost", 0)
            budget = data.get("budget", 0)

            if budget > 0:
                used_percent = min(total_cost / budget, 2.0)  # Cap at 200%
            else:
                used_percent = 0.0

            # Calculate reset time (next billing cycle)
            resets_at = None
            if budget > 0 and total_cost > 0:
                # Estimate days until reset based on spend rate
                daily_spend = total_cost / 30  # Assume 30-day cycle
                if daily_spend > 0:
                    days_left = (budget - total_cost) / daily_spend
                    if days_left > 0:
                        resets_at = datetime.now(timezone.utc) + timedelta(days=days_left)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=43200,  # 30 days in minutes
                resets_at=resets_at,
                reset_description="Monthly budget reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse OpenAI cost report: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity information from usage data.

        Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAIProvider.swift:_parseIdentity()

        Args:
            data: Usage report JSON data

        Returns:
            ProviderIdentitySnapshot with account information
        """
        try:
            # Extract organization name
            org_name = data.get("organization", {}).get("name")
            org_id = data.get("organization", {}).get("id")

            return ProviderIdentitySnapshot(
                account_email=f"{org_name}@openai.com" if org_name else None,
                account_organization=org_name,
                login_method="api_key",
            )

        except Exception as e:
            logger.warning(f"Failed to parse OpenAI identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get API key from environment variables.

        Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAIProvider.swift:getApiKeyFromEnv()

        Checks:
        1. OPENAI_ADMIN_KEY (primary)
        2. OPENAI_API_KEY (fallback)

        Returns:
            API key string or None
        """
        return os.environ.get("OPENAI_ADMIN_KEY") or os.environ.get("OPENAI_API_KEY")

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/OpenAI/OpenAIProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information
        """
        return {
            "provider_id": "openai",
            "name": "OpenAI",
            "description": "OpenAI Organization Usage",
            "linux_support": "full",
            "auth_method": "api_key",
            "config_env_vars": ["OPENAI_ADMIN_KEY", "OPENAI_API_KEY"],
            "dashboard_url": "https://platform.openai.com/usage",
            "status_url": "https://status.openai.com",
        }
