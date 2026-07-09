"""Base provider for CodexBar usage fetching.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/BaseProvider.swift
- Sources/CodexBarCore/Models/RateWindow.swift
- Sources/CodexBarCore/Models/UsageSnapshot.swift

References:
- ProviderDescriptor: Sources/CodexBarCore/Models/ProviderDescriptor.swift
- ProviderStatus: Sources/CodexBarCore/Providers/ProviderStatus.swift
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ProviderStatus(Enum):
    """Provider status codes matching CodexBar's ProviderStatus enum.

    Ported from: Sources/CodexBarCore/Providers/ProviderStatus.swift
    """
    READY = "ready"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    NO_CREDENTIALS = "no_credentials"
    CONFIGURE_NEEDED = "configure_needed"


@dataclass
class RateWindow:
    """Usage rate window data structure.

    Ported from: Sources/CodexBarCore/Models/RateWindow.swift
    """
    used_percent: float  # 0.0 to 1.0 (or >1.0 for over-quota)
    window_minutes: Optional[int] = None
    resets_at: Optional[datetime] = None
    reset_description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "used_percent": self.used_percent,
            "window_minutes": self.window_minutes,
            "resets_at": self.resets_at.isoformat() if self.resets_at else None,
            "reset_description": self.reset_description,
        }


@dataclass
class ProviderIdentitySnapshot:
    """Provider identity information.

    Ported from: Sources/CodexBarCore/Models/ProviderIdentitySnapshot.swift
    """
    account_email: Optional[str] = None
    account_organization: Optional[str] = None
    login_method: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "account_email": self.account_email,
            "account_organization": self.account_organization,
            "login_method": self.login_method,
        }


@dataclass
class UsageSnapshot:
    """Complete usage snapshot result.

    Ported from: Sources/CodexBarCore/Models/UsageSnapshot.swift
    """
    primary: Optional[RateWindow] = None
    secondary: Optional[RateWindow] = None
    tertiary: Optional[RateWindow] = None
    extra_rate_windows: Optional[List[RateWindow]] = field(default_factory=list)
    provider_cost: Optional[Dict[str, Any]] = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    identity: Optional[ProviderIdentitySnapshot] = None
    codex_reset_credits: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "primary": self.primary.to_dict() if self.primary else None,
            "secondary": self.secondary.to_dict() if self.secondary else None,
            "tertiary": self.tertiary.to_dict() if self.tertiary else None,
            "extra_rate_windows": [rw.to_dict() for rw in self.extra_rate_windows],
            "provider_cost": self.provider_cost,
            "updated_at": self.updated_at.isoformat(),
            "identity": self.identity.to_dict() if self.identity else None,
            "codex_reset_credits": self.codex_reset_credits,
        }


class ProviderError(Exception):
    """Base provider error.

    Ported from: Sources/CodexBarCore/Providers/ProviderError.swift
    """
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.code = code or "unknown_error"


class NetworkError(ProviderError):
    """Network request error."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message, f"network_error_{status_code or 'unknown'}")
        self.status_code = status_code


class AuthError(ProviderError):
    """Authentication error."""
    def __init__(self, message: str):
        super().__init__(message, "auth_error")


class ConfigError(ProviderError):
    """Configuration error."""
    def __init__(self, message: str):
        super().__init__(message, "config_error")


class BaseProvider:
    """Abstract base class for all CodexBar providers.

    Ported from: Sources/CodexBarCore/Providers/BaseProvider.swift

    This class defines the interface that all provider implementations must follow.
    It handles common functionality like logging, error handling, and status tracking.
    """

    def __init__(
        self,
        provider_id: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize base provider.

        Args:
            provider_id: Unique identifier for this provider (e.g., "openai", "claude")
            api_key: API key for authentication
            base_url: Base URL for API endpoints
            config: Additional configuration options

        Ported from: Sources/CodexBarCore/Providers/BaseProvider.swift:init
        """
        self.provider_id = provider_id
        self.api_key = api_key
        self.base_url = base_url
        self.config = config or {}
        self.status = ProviderStatus.READY
        self.last_error: Optional[ProviderError] = None
        self._logger = logging.getLogger(f"providers.{provider_id}")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch usage data from the provider.

        This is the main method that all providers must implement.

        Ported from: Sources/CodexBarCore/Providers/BaseProvider.swift:fetchUsage()

        Returns:
            UsageSnapshot with rate windows and identity information

        Raises:
            ProviderError: If fetching fails
        """
        raise NotImplementedError("Subclasses must implement fetch_usage()")

    async def _fetch_with_retry(
        self,
        fetch_func,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> Any:
        """Fetch data with retry logic.

        Ported from: Sources/CodexBarCore/Providers/BaseProvider.swift:_fetchWithRetry()

        Implements exponential backoff with jitter, matching CodexBar's retry pattern.

        Args:
            fetch_func: Async function to call
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds for exponential backoff

        Returns:
            Result from fetch_func

        Raises:
            ProviderError: If all retries fail
        """
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                return await fetch_func()
            except Exception as e:
                last_error = e
                if isinstance(e, AuthError):
                    self.status = ProviderStatus.NO_CREDENTIALS
                    self._logger.warning(
                        f"{self.provider_id}: Auth error after attempt {attempt + 1}: {e}"
                    )
                    break
                elif attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    jitter = asyncio.get_event_loop().time() * 1000 % 1000 / 1000
                    sleep_time = delay + jitter
                    self._logger.info(
                        f"{self.provider_id}: Retry {attempt + 1}/{max_retries} "
                        f"after {sleep_time:.2f}s delay: {e}"
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    self._logger.error(
                        f"{self.provider_id}: All {max_retries + 1} attempts failed: {e}"
                    )

        self.status = ProviderStatus.ERROR
        self.last_error = ProviderError(
            f"Max retries exceeded: {last_error}",
            "max_retries_exceeded"
        )
        raise self.last_error

    def _get_api_key(self) -> str:
        """Get API key from config or environment.

        Ported from: Sources/CodexBarCore/Providers/BaseProvider.swift:_getApiKey()

        Returns:
            API key string

        Raises:
            ConfigError: If API key not found
        """
        if self.api_key:
            return self.api_key

        env_var = self.config.get("api_key_env")
        if env_var and os.environ.get(env_var):
            return os.environ[env_var]

        raise ConfigError(
            f"API key not found for provider {self.provider_id}. "
            f"Set the API key in config or environment variable {env_var}."
        )

    def _validate_endpoint(self, endpoint: str) -> str:
        """Validate and construct API endpoint URL.

        Ported from: Sources/CodexBarCore/Providers/BaseProvider.swift:_validateEndpoint()

        Args:
            endpoint: API endpoint path

        Returns:
            Full URL string
        """
        if not self.base_url:
            return endpoint
        base = self.base_url.rstrip("/")
        path = endpoint.lstrip("/")
        # Avoid /v1/v1 when base already includes the version prefix.
        if base.endswith("/v1") and (path == "v1" or path.startswith("v1/")):
            path = path[3:].lstrip("/")
        return f"{base}/{path}" if path else base

    def _create_auth_headers(self, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Create authentication headers.

        Ported from: Sources/CodexBarCore/Providers/BaseProvider.swift:_createAuthHeaders()

        Args:
            extra_headers: Additional headers to include

        Returns:
            Headers dictionary with authentication
        """
        headers = extra_headers or {}

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        headers["User-Agent"] = "CodexBar-Python/1.0"
        headers["Accept"] = "application/json"

        return headers

    def _handle_response_error(self, response: Any) -> None:
        """Handle HTTP response errors.

        Ported from: Sources/CodexBarCore/Providers/BaseProvider.swift:_handleResponseError()

        Args:
            response: HTTP response object

        Raises:
            NetworkError: For network failures
            AuthError: For authentication failures
            ProviderError: For other errors
        """
        if hasattr(response, 'status_code'):
            status_code = response.status_code

            if status_code == 401:
                raise AuthError(f"Authentication failed (401)")
            elif status_code == 403:
                raise AuthError(f"Access forbidden (403)")
            elif status_code == 429:
                raise NetworkError(f"Rate limit exceeded (429)", status_code)
            elif status_code >= 500:
                raise NetworkError(f"Server error: {status_code}", status_code)

    def to_dict(self) -> Dict[str, Any]:
        """Convert provider info to dictionary.

        Ported from: Sources/CodexBarCore/Providers/BaseProvider.swift:toDictionary()

        Returns:
            Dictionary with provider metadata
        """
        return {
            "provider_id": self.provider_id,
            "status": self.status.value,
            "has_api_key": bool(self.api_key),
            "base_url": self.base_url,
            "last_error": str(self.last_error) if self.last_error else None,
        }

    def __str__(self) -> str:
        """String representation of provider."""
        return f"{self.provider_id} ({self.status.value})"

    def __repr__(self) -> str:
        """Repr of provider."""
        return f"{self.__class__.__name__}(provider_id={self.provider_id!r})"
