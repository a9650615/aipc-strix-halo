"""OpenRouter provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/OpenRouter/OpenRouterProvider.swift
- Sources/CodexBarCore/Providers/OpenRouter/OpenRouterKeyInfo.swift
- Sources/CodexBarCore/Providers/OpenRouter/OpenRouterRateLimits.swift

References:
- API Endpoints: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterProvider.swift
- Auth: Bearer token (OpenRouter API key)
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

# OpenRouter API base URL.
OPENROUTER_API_BASE = "https://openrouter.ai/api"
# Key info endpoint.
OPENROUTER_KEY_INFO_PATH = "/v1/auth/key"


class OpenRouterProvider(BaseProvider):
    """OpenRouter provider using key info and credits API.

    Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterProvider.swift

    Supports:
    - Bearer token authentication (OpenRouter API key)
    - Key info (credits, rate limits)
    - Auth key details

    Linux Support: full
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = OPENROUTER_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize OpenRouter provider.

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterProvider.swift:init

        Args:
            api_key: OpenRouter API key (Bearer token).
            base_url: Base URL for OpenRouter API.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="openrouter",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self._logger = logging.getLogger(f"providers.openrouter")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch OpenRouter key info and rate limits.

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterProvider.swift:fetchUsage()

        Makes two parallel requests:
        1. Key info (credits, spending limit)
        2. Auth key details (rate limits, model access)

        Returns:
            UsageSnapshot with primary (credits) and extra rate windows (rate limits).

        Raises:
            AuthError: If API key is invalid.
            NetworkError: If API request fails.
        """
        self.status = ProviderStatus.READY

        try:
            key_info, auth_key = await self._fetch_parallel()

            primary_window = self._parse_credits(key_info)
            extra_windows = self._parse_rate_limits(auth_key)
            identity = self._parse_identity(key_info)

            return UsageSnapshot(
                primary=primary_window,
                extra_rate_windows=extra_windows,
                identity=identity,
                updated_at=datetime.now(timezone.utc),
            )

        except ProviderError:
            raise
        except Exception as e:
            self.status = ProviderStatus.ERROR
            self.last_error = ProviderError(f"Failed to fetch OpenRouter usage: {e}")
            raise self.last_error

    async def _fetch_parallel(self) -> tuple:
        """Fetch key info and auth key details in parallel.

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterProvider.swift:_fetchParallel()

        Returns:
            Tuple of (key_info, auth_key).

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = self._create_auth_headers()
            headers["Authorization"] = f"Bearer {self.api_key or ''}"

            key_info = await self._fetch_key_info(client, headers)
            auth_key = await self._fetch_auth_key(client, headers)

            return key_info, auth_key

    async def _fetch_key_info(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch key info (credits, spending limit).

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterKeyInfo.swift:fetchKeyInfo()

        Endpoint: GET /v1/key/info
        Auth: Authorization: Bearer <api_key>

        Returns:
            Key info JSON with credits and spending data.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint("/v1/key/info")

        try:
            response = await client.get(url, headers=headers)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid OpenRouter API key")

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

    async def _fetch_auth_key(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Fetch auth key details (rate limits, model access).

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterRateLimits.swift

        Endpoint: GET /v1/auth/key
        Auth: Authorization: Bearer <api_key>

        Returns:
            Auth key JSON with rate limit information.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(OPENROUTER_KEY_INFO_PATH)

        try:
            response = await client.get(url, headers=headers)
            self._handle_response_error(response)

            if response.status_code == 401:
                raise AuthError("Invalid OpenRouter API key")

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self._handle_response_error(e.response)
            raise NetworkError(
                f"Auth key request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Auth key request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Auth key request error: {e}")

    def _parse_credits(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse credits data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterKeyInfo.swift:parseCredits()

        OpenRouter uses a credit-based system with spending limits.

        Args:
            data: Key info JSON data.

        Returns:
            RateWindow with credits remaining percentage.
        """
        try:
            # Extract credit and spending information.
            credits = data.get("credits", 0)
            spending_limit = data.get("spending_limit", 0)
            amount_used = data.get("amount_used", 0)

            if spending_limit > 0:
                remaining = spending_limit - amount_used
                used_percent = min(amount_used / spending_limit, 2.0)
            elif credits > 0:
                # For credit-based accounts, show remaining credits.
                used_percent = 0.0
                remaining = credits
            else:
                used_percent = 0.0
                remaining = 0

            # Estimate time until next top-up or reset.
            resets_at = None
            window_minutes = None

            if spending_limit > 0 and amount_used > 0:
                # Estimate daily spend rate from usage period.
                days_active = data.get("days_active", 30)
                if days_active > 0:
                    daily_spend = amount_used / days_active
                    if daily_spend > 0 and remaining > 0:
                        hours_left = (remaining / daily_spend) * 24
                        resets_at = datetime.now(timezone.utc) + timedelta(
                            minutes=int(hours_left * 60)
                        )
                        window_minutes = int(hours_left * 60)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=window_minutes,
                resets_at=resets_at,
                reset_description=f"OpenRouter credits/spending limit",
            )

        except Exception as e:
            logger.warning(f"Failed to parse OpenRouter credits: {e}")
            return None

    def _parse_rate_limits(self, data: Dict[str, Any]) -> List[RateWindow]:
        """Parse rate limit data into extra RateWindows.

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterRateLimits.swift:_parseRateLimits()

        Creates a rate window for each rate limit category reported.

        Args:
            data: Auth key JSON data with rate limits.

        Returns:
            List of RateWindow objects for each rate limit.
        """
        windows = []

        try:
            # Extract rate limit information.
            rate_limits = data.get("rate_limits", {})

            # TPM (tokens per minute) limit.
            tpm = rate_limits.get("tpm", {})
            if tpm:
                tpm_limit = tpm.get("limit", 0)
                tpm_used = tpm.get("used", 0)
                if tpm_limit > 0:
                    windows.append(RateWindow(
                        used_percent=min(tpm_used / tpm_limit, 2.0),
                        window_minutes=1,  # 1 minute window
                        reset_description="TPM (tokens per minute) resets every minute",
                    ))

            # RPM (requests per minute) limit.
            rpm = rate_limits.get("rpm", {})
            if rpm:
                rpm_limit = rpm.get("limit", 0)
                rpm_used = rpm.get("used", 0)
                if rpm_limit > 0:
                    windows.append(RateWindow(
                        used_percent=min(rpm_used / rpm_limit, 2.0),
                        window_minutes=1,  # 1 minute window
                        reset_description="RPM (requests per minute) resets every minute",
                    ))

            return windows

        except Exception as e:
            logger.warning(f"Failed to parse OpenRouter rate limits: {e}")
            return windows

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from key info data.

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterProvider.swift:_parseIdentity()

        Args:
            data: Key info JSON data.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            # Extract user and key metadata.
            key_info = data.get("key", {})
            user = data.get("user", {})

            email = user.get("email")
            key_name = key_info.get("name", key_info.get("prefix", ""))

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=key_name or None,
                login_method="api_key",
            )

        except Exception as e:
            logger.warning(f"Failed to parse OpenRouter identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get API key from environment variables.

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterProvider.swift:getApiKeyFromEnv()

        Checks:
        1. OPENROUTER_API_KEY (primary)

        Returns:
            API key string or None.
        """
        return os.environ.get("OPENROUTER_API_KEY")

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/OpenRouter/OpenRouterProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "openrouter",
            "name": "OpenRouter",
            "description": "OpenRouter Credits & Rate Limits",
            "linux_support": "full",
            "auth_method": "bearer_token",
            "config_env_vars": ["OPENROUTER_API_KEY"],
            "dashboard_url": "https://openrouter.ai/keys",
            "status_url": "https://status.openrouter.ai",
        }
