"""Warp provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/Warp/WarpProvider.swift
- Sources/CodexBarCore/Providers/Warp/WarpGraphQLAPI.swift
- Sources/CodexBarCore/Providers/Warp/WarpUsageQuery.swift

References:
- API: https://api.warp.dev/graphql
- Auth: Bearer token (Warp API token)
- Linux Support: full
"""

import json
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

# Warp API base URL.
WARP_API_BASE = "https://api.warp.dev"
# GraphQL endpoint.
WARP_GRAPHQL_PATH = "/graphql"
# Warp usage GraphQL query.
WARP_USAGE_QUERY = """
query WarpUsage($timeRange: TimeRangeInput!) {
  usage(timeRange: $timeRange) {
    totalMessages
    totalTokens
    limits {
      maxMessages
      maxTokens
    }
  }
  me {
    email
    displayName
    plan {
      name
      type
    }
  }
}
"""
# Warp identity GraphQL query.
WARP_IDENTITY_QUERY = """
query WarpIdentity {
  me {
    email
    displayName
    id
    plan {
      name
      type
      organizationId
    }
  }
}
"""


class WarpProvider(BaseProvider):
    """Warp provider using GraphQL API.

    Ported from: Sources/CodexBarCore/Providers/Warp/WarpProvider.swift

    Warp is a GPU-accelerated terminal with built-in AI capabilities.
    Usage is tracked via a GraphQL endpoint.

    Supports:
    - GraphQL API for usage and identity queries
    - Bearer token authentication (Warp API token)
    - Message count and token usage tracking
    - Plan and limit information

    Linux Support: full
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = WARP_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Warp provider.

        Ported from: Sources/CodexBarCore/Providers/Warp/WarpProvider.swift:init

        Args:
            api_key: Warp API token (Bearer token).
            base_url: Base URL for Warp API.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="warp",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self._logger = logging.getLogger(f"providers.warp")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch Warp usage data via GraphQL.

        Ported from: Sources/CodexBarCore/Providers/Warp/WarpProvider.swift:fetchUsage()

        Strategy:
        1. Build GraphQL request with time range.
        2. Query usage and identity in a single GraphQL call.
        3. Parse response into rate windows.

        Returns:
            UsageSnapshot with primary (monthly messages) and secondary
            (monthly tokens) rate windows and identity.

        Raises:
            AuthError: If API token is invalid.
            NetworkError: If GraphQL request fails.
        """
        self.status = ProviderStatus.READY

        try:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {self.api_key or ''}"
            headers["Content-Type"] = "application/json"

            # Calculate time range for the query (last 30 days).
            now = datetime.now(timezone.utc)
            start = now - timedelta(days=30)
            time_range = {
                "start": start.isoformat(),
                "end": now.isoformat(),
            }

            # Build GraphQL request body.
            query_body = {
                "query": WARP_USAGE_QUERY,
                "variables": {"timeRange": time_range},
            }

            usage_data = await self._graphql_request(headers, query_body)

            primary_window = self._parse_message_usage(usage_data)
            secondary_window = self._parse_token_usage(usage_data)
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
            self.last_error = ProviderError(f"Failed to fetch Warp usage: {e}")
            raise self.last_error

    async def _graphql_request(
        self, headers: Dict[str, str], query_body: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send GraphQL request to Warp API.

        Ported from: Sources/CodexBarCore/Providers/Warp/WarpGraphQLAPI.swift:graphqlRequest()

        Endpoint: POST /graphql
        Auth: Authorization: Bearer <token>

        Args:
            headers: Request headers.
            query_body: GraphQL query body.

        Returns:
            GraphQL response data.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(WARP_GRAPHQL_PATH)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=query_body)
                self._handle_response_error(response)

                if response.status_code == 401:
                    raise AuthError("Invalid Warp API token")
                if response.status_code == 403:
                    raise AuthError("Warp API token lacks usage access")

                response.raise_for_status()
                result = response.json()

                # Handle GraphQL errors.
                if "errors" in result:
                    errors = result["errors"]
                    error_msg = "; ".join(
                        e.get("message", str(e)) for e in errors
                    )
                    raise ProviderError(f"Warp GraphQL errors: {error_msg}", "graphql_error")

                return result.get("data", {})

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"GraphQL request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("GraphQL request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"GraphQL request error: {e}")

    def _parse_message_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse message usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Warp/WarpUsageQuery.swift:parseMessageUsage()

        Warp tracks the number of AI messages sent per month.

        Args:
            data: GraphQL response data.

        Returns:
            RateWindow with monthly message usage percentage.
        """
        try:
            usage = data.get("usage", {})
            total_messages = usage.get("totalMessages", 0)
            limits = usage.get("limits", {})
            max_messages = limits.get("maxMessages", 0)

            if max_messages > 0:
                used_percent = min(total_messages / max_messages, 2.0)
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
                reset_description="Warp monthly message quota reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Warp message usage: {e}")
            return None

    def _parse_token_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse token usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Warp/WarpUsageQuery.swift:parseTokenUsage()

        Warp also tracks total tokens consumed per month.

        Args:
            data: GraphQL response data.

        Returns:
            RateWindow with monthly token usage percentage.
        """
        try:
            usage = data.get("usage", {})
            total_tokens = usage.get("totalTokens", 0)
            limits = usage.get("limits", {})
            max_tokens = limits.get("maxTokens", 0)

            if max_tokens > 0:
                used_percent = min(total_tokens / max_tokens, 2.0)
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
                reset_description="Warp monthly token quota reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Warp token usage: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from Warp data.

        Ported from: Sources/CodexBarCore/Providers/Warp/WarpProvider.swift:_parseIdentity()

        Args:
            data: GraphQL response data.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            user = data.get("me", {})
            email = user.get("email")
            name = user.get("displayName")
            plan_data = user.get("plan", {})
            plan_name = plan_data.get("name", "unknown")
            org_id = plan_data.get("organizationId")

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=plan_name if plan_name != "unknown" else None,
                login_method="api_token",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Warp identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get API token from environment variables.

        Ported from: Sources/CodexBarCore/Providers/Warp/WarpProvider.swift:getApiKeyFromEnv()

        Checks:
        1. WARP_API_KEY (primary)
        2. WARP_TOKEN (fallback)

        Returns:
            API token string or None.
        """
        return os.environ.get("WARP_API_KEY") or os.environ.get("WARP_TOKEN")

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/Warp/WarpProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "warp",
            "name": "Warp",
            "description": "Warp Terminal AI Usage (GraphQL)",
            "linux_support": "full",
            "auth_method": "bearer_token",
            "config_env_vars": ["WARP_API_KEY", "WARP_TOKEN"],
            "dashboard_url": "https://warp.dev/settings/billing",
            "status_url": "https://status.warp.dev",
        }
