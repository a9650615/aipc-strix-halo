"""LiteLLM provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProvider.swift
- Sources/CodexBarCore/Providers/LiteLLM/LiteLLMAggregator.swift
- Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProxyAPI.swift

References:
- Proxy API: /v1/key/info and /v1/user/info
- Auth: Bearer token + base URL config
- Linux Support: full
"""

import logging
import os
from datetime import datetime, timezone
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

# Default LiteLLM proxy base URL.
LITELLM_PROXY_DEFAULT = "http://localhost:4000"


class LiteLLMProvider(BaseProvider):
    """LiteLLM proxy provider for aggregated budget tracking.

    Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProvider.swift

    Supports:
    - Proxy API key info (/v1/key/info) for individual key budgets
    - User info (/v1/user/info) for team/personal budgets
    - Aggregation of personal and team budgets through a single proxy

    Linux Support: full
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = LITELLM_PROXY_DEFAULT,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize LiteLLM provider.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProvider.swift:init

        Args:
            api_key: LiteLLM proxy API key (Bearer token).
            base_url: LiteLLM proxy base URL.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="litellm",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self._logger = logging.getLogger(f"providers.litellm")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch LiteLLM aggregated budget info.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProvider.swift:fetchUsage()

        Makes two parallel requests:
        1. Key info (/v1/key/info) for individual key spending limits.
        2. User info (/v1/user/info) for team/personal budgets.

        Returns:
            UsageSnapshot with primary (key budget) and secondary (user budget) windows.

        Raises:
            AuthError: If API key is invalid.
            NetworkError: If proxy is unreachable.
        """
        self.status = ProviderStatus.READY

        try:
            key_info, user_info = await self._fetch_parallel()

            key_window = self._parse_key_info(key_info)
            user_window = self._parse_user_info(user_info)
            identity = self._parse_identity(user_info)

            return UsageSnapshot(
                primary=key_window,
                secondary=user_window,
                identity=identity,
                updated_at=datetime.now(timezone.utc),
            )

        except ProviderError:
            raise
        except Exception as e:
            self.status = ProviderStatus.ERROR
            self.last_error = ProviderError(f"Failed to fetch LiteLLM usage: {e}")
            raise self.last_error

    async def _fetch_parallel(self) -> tuple:
        """Fetch key info and user info in parallel.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMAggregator.swift:_fetchParallel()

        Returns:
            Tuple of (key_info, user_info).

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {self.api_key or ''}"

            key_info = await self._fetch_key_info(client, headers)
            user_info = await self._fetch_user_info(client, headers)

            return key_info, user_info

    async def _fetch_key_info(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch key info from LiteLLM proxy.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProxyAPI.swift:fetchKeyInfo()

        Endpoint: GET /v1/key/info
        Auth: Authorization: Bearer <proxy_api_key>

        Returns:
            Key info JSON with spending limits and usage.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint("/v1/key/info")

        try:
            response = await client.get(url, headers=headers)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid LiteLLM proxy API key")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Key info request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Key info request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Key info request error: {e}")

    async def _fetch_user_info(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch user info from LiteLLM proxy.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProxyAPI.swift:fetchUserInfo()

        Endpoint: GET /v1/user/info
        Auth: Authorization: Bearer <proxy_api_key>

        Returns:
            User info JSON with team and personal budgets.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint("/v1/user/info")

        try:
            response = await client.get(url, headers=headers)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid LiteLLM proxy API key")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"User info request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("User info request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"User info request error: {e}")

    def _parse_key_info(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse key info data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProxyAPI.swift:_parseKeyInfo()

        The key budget represents the individual API key's spending limit.

        Args:
            data: Key info JSON data.

        Returns:
            RateWindow with key budget usage percentage.
        """
        try:
            # Extract key spending information.
            spend = data.get("spend", 0)
            limit = data.get("max_budget", data.get("budget_limit", 0))
            currency = data.get("currency", "USD")

            if limit > 0:
                used_percent = min(spend / limit, 2.0)
            else:
                used_percent = 0.0

            return RateWindow(
                used_percent=used_percent,
                window_minutes=None,
                resets_at=None,
                reset_description=f"LiteLLM key budget ({currency})",
            )

        except Exception as e:
            logger.warning(f"Failed to parse LiteLLM key info: {e}")
            return None

    def _parse_user_info(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse user info data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMAggregator.swift:_parseUserInfo()

        The user budget aggregates team and personal spending limits.

        Args:
            data: User info JSON data.

        Returns:
            RateWindow with user budget usage percentage.
        """
        try:
            # Extract user/team spending information.
            user_spend = data.get("spend", 0)
            user_limit = data.get("max_budget", data.get("budget_limit", 0))

            # Team-level budget if available.
            team_spend = data.get("team_spend", 0)
            team_limit = data.get("team_budget", 0)

            # Use the larger of user or team limits as the primary reference.
            if user_limit > 0 or team_limit > 0:
                total_limit = max(user_limit, team_limit)
                total_spend = max(user_spend, team_spend)
                used_percent = min(total_spend / total_limit, 2.0)
            else:
                used_percent = 0.0

            return RateWindow(
                used_percent=used_percent,
                window_minutes=None,
                resets_at=None,
                reset_description="LiteLLM user/team budget",
            )

        except Exception as e:
            logger.warning(f"Failed to parse LiteLLM user info: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from user info data.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProvider.swift:_parseIdentity()

        Args:
            data: User info JSON data.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            user = data.get("user", {})
            email = user.get("user_email") or user.get("email")
            team = user.get("team", {}).get("team_name")

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=team,
                login_method="proxy_api_key",
            )

        except Exception as e:
            logger.warning(f"Failed to parse LiteLLM identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get API key from environment variables.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProvider.swift:getApiKeyFromEnv()

        Checks:
        1. LITELLM_API_KEY (primary)
        2. LITELLM_PROXY_KEY (fallback)

        Returns:
            API key string or None.
        """
        return (
            os.environ.get("LITELLM_API_KEY")
            or os.environ.get("LITELLM_PROXY_KEY")
        )

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/LiteLLM/LiteLLMProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "litellm",
            "name": "LiteLLM",
            "description": "LiteLLM Proxy Budget Aggregator",
            "linux_support": "full",
            "auth_method": "bearer_token",
            "config_env_vars": ["LITELLM_API_KEY", "LITELLM_PROXY_KEY"],
            "dashboard_url": None,
            "status_url": None,
        }
