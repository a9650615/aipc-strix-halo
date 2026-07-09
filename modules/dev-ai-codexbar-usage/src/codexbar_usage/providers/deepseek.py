"""DeepSeek provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/DeepSeek/DeepSeekProvider.swift
- Sources/CodexBarCore/Providers/DeepSeek/DeepSeekBalanceAPI.swift

References:
- API Endpoints: Sources/CodexBarCore/Providers/DeepSeek/DeepSeekProvider.swift
- Auth: Bearer token (DeepSeek API key)
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

# DeepSeek API base URL.
DEEPSEEK_API_BASE = "https://api.deepseek.com"
# Balance endpoint.
DEEPSEEK_BALANCE_PATH = "/balance"


class DeepSeekProvider(BaseProvider):
    """DeepSeek provider using balance API.

    Ported from: Sources/CodexBarCore/Providers/DeepSeek/DeepSeekProvider.swift

    Supports:
    - Bearer token authentication (DeepSeek API key)
    - Balance queries with paid/granted breakdown
    - Account identity information

    Linux Support: full
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEEPSEEK_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize DeepSeek provider.

        Ported from: Sources/CodexBarCore/Providers/DeepSeek/DeepSeekProvider.swift:init

        Args:
            api_key: DeepSeek API key (Bearer token).
            base_url: Base URL for DeepSeek API.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="deepseek",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self._logger = logging.getLogger(f"providers.deepseek")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch DeepSeek account balance.

        Ported from: Sources/CodexBarCore/Providers/DeepSeek/DeepSeekProvider.swift:fetchUsage()

        Calls /balance endpoint to get current balance and breakdown.

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
            self.last_error = ProviderError(f"Failed to fetch DeepSeek balance: {e}")
            raise self.last_error

    async def _fetch_balance(self) -> Dict[str, Any]:
        """Fetch balance from DeepSeek API.

        Ported from: Sources/CodexBarCore/Providers/DeepSeek/DeepSeekBalanceAPI.swift:fetchBalance()

        Endpoint: GET /balance
        Auth: Authorization: Bearer <api_key>

        Returns:
            Balance data JSON with balance, paid, and granted breakdown.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(DEEPSEEK_BALANCE_PATH)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = self._create_auth_headers()
                headers["Authorization"] = f"Bearer {self.api_key or ''}"

                response = await client.get(url, headers=headers)
                self._handle_response_error(response)

                if response.status_code == 401:
                    raise AuthError("Invalid DeepSeek API key")

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

        Ported from: Sources/CodexBarCore/Providers/DeepSeek/DeepSeekProvider.swift:_parseBalance()

        DeepSeek uses a prepaid credit system with paid and granted breakdowns.
        The rate window represents the remaining balance relative to the original
        top-up amount or total credit.

        Args:
            data: Balance API response JSON.

        Returns:
            RateWindow with remaining balance percentage.
        """
        try:
            # Extract balance information.
            balance = data.get("balance", 0)
            paid_balance = data.get("paid_balance", 0)
            granted_balance = data.get("granted_balance", 0)
            total_balance = data.get("total_balance", balance)

            # Calculate total credit (balance + spent).
            # DeepSeek may report this differently; use balance as the reference.
            spent = data.get("total_spent", 0)
            total_credit = total_balance + spent if total_balance > 0 else total_balance

            if total_credit > 0:
                # used_percent represents how much of the total credit has been consumed.
                used_percent = min(spent / total_credit, 2.0)
            else:
                used_percent = 0.0

            # DeepSeek credits do not have a fixed reset window.
            # Report the balance as remaining for informational purposes.
            return RateWindow(
                used_percent=used_percent,
                window_minutes=None,
                resets_at=None,
                reset_description="Prepaid credits, no fixed reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse DeepSeek balance: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from balance data.

        Ported from: Sources/CodexBarCore/Providers/DeepSeek/DeepSeekProvider.swift:_parseIdentity()

        Args:
            data: Balance API response JSON.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            user = data.get("user", {})
            email = user.get("email")
            username = user.get("username")

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=None,
                login_method="api_key",
            )

        except Exception as e:
            logger.warning(f"Failed to parse DeepSeek identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get API key from environment variables.

        Ported from: Sources/CodexBarCore/Providers/DeepSeek/DeepSeekProvider.swift:getApiKeyFromEnv()

        Checks:
        1. DEEPSEEK_API_KEY (primary)

        Returns:
            API key string or None.
        """
        return os.environ.get("DEEPSEEK_API_KEY")

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/DeepSeek/DeepSeekProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "deepseek",
            "name": "DeepSeek",
            "description": "DeepSeek Balance (Paid/Granted)",
            "linux_support": "full",
            "auth_method": "bearer_token",
            "config_env_vars": ["DEEPSEEK_API_KEY"],
            "dashboard_url": "https://platform.deepseek.com/usage",
            "status_url": "https://status.deepseek.com",
        }
