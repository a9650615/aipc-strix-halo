"""Moonshot provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/Moonshot/MoonshotProvider.swift
- Sources/CodexBarCore/Providers/Moonshot/MoonshotBalanceAPI.swift

References:
- API: https://api.moonshot.cn/v1/balance
- Auth: Bearer token (Moonshot API key, prefix: sk-...)
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

# Moonshot API base URL.
MOONSHOT_API_BASE = "https://api.moonshot.cn/v1"
# Balance endpoint.
MOONSHOT_BALANCE_PATH = "/balance"


class MoonshotProvider(BaseProvider):
    """Moonshot provider using balance API.

    Ported from: Sources/CodexBarCore/Providers/Moonshot/MoonshotProvider.swift

    Moonshot AI is a Chinese AI company providing language models via API.
    The balance endpoint shows account credit status.

    Supports:
    - Bearer token authentication (Moonshot API key)
    - Balance queries with credit breakdown
    - Account identity information

    Linux Support: full
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = MOONSHOT_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Moonshot provider.

        Ported from: Sources/CodexBarCore/Providers/Moonshot/MoonshotProvider.swift:init

        Args:
            api_key: Moonshot API key (Bearer token, prefix: sk-...).
            base_url: Base URL for Moonshot API.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="moonshot",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self._logger = logging.getLogger(f"providers.moonshot")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch Moonshot account balance.

        Ported from: Sources/CodexBarCore/Providers/Moonshot/MoonshotProvider.swift:fetchUsage()

        Calls the Moonshot balance endpoint to get current credits.

        Returns:
            UsageSnapshot with primary rate window and identity.

        Raises:
            AuthError: If API key is invalid.
            NetworkError: If API request fails.
        """
        self.status = ProviderStatus.READY

        try:
            balance_data = await self._fetch_balance()

            primary_window = self._parse_balance(balance_data)
            identity = self._parse_identity(balance_data)

            return UsageSnapshot(
                primary=primary_window,
                identity=identity,
                updated_at=datetime.now(timezone.utc),
            )

        except ProviderError:
            raise
        except Exception as e:
            self.status = ProviderStatus.ERROR
            self.last_error = ProviderError(f"Failed to fetch Moonshot balance: {e}")
            raise self.last_error

    async def _fetch_balance(self) -> Dict[str, Any]:
        """Fetch balance from Moonshot API.

        Ported from: Sources/CodexBarCore/Providers/Moonshot/MoonshotBalanceAPI.swift:fetchBalance()

        Endpoint: GET /v1/balance
        Auth: Authorization: Bearer <api_key>

        Returns:
            Balance data JSON with credit information.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(MOONSHOT_BALANCE_PATH)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = self._create_auth_headers()
                headers["Authorization"] = f"Bearer {self.api_key or ''}"

                response = await client.get(url, headers=headers)
                self._handle_response_error(response)

                if response.status_code == 401:
                    raise AuthError("Invalid Moonshot API key")
                if response.status_code == 403:
                    raise AuthError("Moonshot API key lacks balance access")

                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Balance request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Balance request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Balance request error: {e}")

    def _parse_balance(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse balance data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Moonshot/MoonshotProvider.swift:_parseBalance()

        Moonshot uses a prepaid credit system. The rate window represents
        the remaining credit relative to the total credit available.

        Args:
            data: Balance API response JSON.

        Returns:
            RateWindow with remaining credit percentage.
        """
        try:
            # Extract balance information.
            # Moonshot balance API fields.
            total_balance = data.get("balance", data.get("total_balance", 0))
            available = data.get("available", data.get("available_balance", 0))
            frozen = data.get("frozen", data.get("frozen_balance", 0))
            total_credit = data.get("total_credit", 0)

            # Calculate spending percentage.
            if total_credit > 0:
                spent = total_credit - available - frozen
                used_percent = min(max(spent / total_credit, 0.0), 2.0)
            elif total_balance > 0:
                # Fallback: treat balance as the reference.
                used_percent = 0.0
            else:
                used_percent = 0.0

            # Credits do not have a fixed reset window.
            return RateWindow(
                used_percent=used_percent,
                window_minutes=None,
                resets_at=None,
                reset_description="Moonshot prepaid credits, no fixed reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Moonshot balance: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from balance data.

        Ported from: Sources/CodexBarCore/Providers/Moonshot/MoonshotProvider.swift:_parseIdentity()

        Args:
            data: Balance API response JSON.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            user = data.get("user", {})
            email = user.get("email", user.get("account_email", ""))
            username = user.get("username", user.get("account_name", ""))
            phone = user.get("phone", "")

            return ProviderIdentitySnapshot(
                account_email=email or phone or None,
                account_organization=username or None,
                login_method="api_key",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Moonshot identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get API key from environment variables.

        Ported from: Sources/CodexBarCore/Providers/Moonshot/MoonshotProvider.swift:getApiKeyFromEnv()

        Checks:
        1. MOONSHOT_API_KEY (primary)

        Returns:
            API key string or None.
        """
        return os.environ.get("MOONSHOT_API_KEY")

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/Moonshot/MoonshotProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "moonshot",
            "name": "Moonshot",
            "description": "Moonshot AI Balance",
            "linux_support": "full",
            "auth_method": "bearer_token",
            "config_env_vars": ["MOONSHOT_API_KEY"],
            "dashboard_url": "https://platform.moonshot.cn/console/billing/overview",
            "status_url": "https://status.moonshot.cn",
        }
