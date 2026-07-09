"""GitHub Copilot provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/Copilot/CopilotProvider.swift
- Sources/CodexBarCore/Providers/Copilot/CopilotInternalAPI.swift
- Sources/CodexBarCore/Providers/Copilot/CopilotPlanInfo.swift

References:
- API Endpoints: Sources/CodexBarCore/Providers/Copilot/CopilotProvider.swift
- Auth: Bearer token (GitHub token)
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

# GitHub Copilot internal API base URL.
COPILOT_API_BASE = "https://api.github.com"
# Copilot usage endpoint.
COPILOT_USAGE_PATH = "/copilot_internal/user"


class CopilotProvider(BaseProvider):
    """GitHub Copilot provider using internal API.

    Ported from: Sources/CodexBarCore/Providers/Copilot/CopilotProvider.swift

    Supports:
    - Bearer token authentication (GitHub personal access token)
    - Plan info and usage metrics via internal API
    - Session and monthly rate windows

    Linux Support: full
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = COPILOT_API_BASE,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Copilot provider.

        Ported from: Sources/CodexBarCore/Providers/Copilot/CopilotProvider.swift:init

        Args:
            api_key: GitHub personal access token.
            base_url: Base URL for GitHub API.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="copilot",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self._logger = logging.getLogger(f"providers.copilot")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch Copilot plan and usage info.

        Ported from: Sources/CodexBarCore/Providers/Copilot/CopilotProvider.swift:fetchUsage()

        Steps:
        1. Query internal user endpoint for plan and usage.
        2. Parse plan limits and current usage.

        Returns:
            UsageSnapshot with primary (monthly) rate window and identity.

        Raises:
            AuthError: If token is invalid.
            NetworkError: If API request fails.
        """
        self.status = ProviderStatus.READY

        try:
            user_data = await self._fetch_user_info()

            primary_window = self._parse_usage(user_data)
            identity = self._parse_identity(user_data)

            return UsageSnapshot(
                primary=primary_window,
                identity=identity,
                updated_at=datetime.now(timezone.utc),
            )

        except ProviderError:
            raise
        except Exception as e:
            self.status = ProviderStatus.ERROR
            self.last_error = ProviderError(f"Failed to fetch Copilot usage: {e}")
            raise self.last_error

    async def _fetch_user_info(self) -> Dict[str, Any]:
        """Fetch user plan and usage from Copilot internal API.

        Ported from: Sources/CodexBarCore/Providers/Copilot/CopilotInternalAPI.swift:fetchUserInfo()

        Endpoint: GET /copilot_internal/user
        Auth: Bearer <github_token>

        Returns:
            User data JSON with plan and usage information.

        Raises:
            NetworkError: On request failure.
            AuthError: On authentication failure.
        """
        url = self._validate_endpoint(COPILOT_USAGE_PATH)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = self._create_auth_headers()
                # Copilot internal API uses X-Token header pattern.
                headers["Authorization"] = f"Bearer {self.api_key or ''}"
                headers["Accept"] = "application/json"
                headers["X-GitHub-Api-Version"] = "2022-11-28"

                response = await client.get(url, headers=headers)
                self._handle_response_error(response)

                if response.status_code == 401:
                    raise AuthError("Invalid GitHub token for Copilot")
                if response.status_code == 403:
                    raise AuthError("GitHub token lacks Copilot access scope")

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

    def _parse_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse user plan and usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Copilot/CopilotPlanInfo.swift:parseUsage()

        Extracts monthly chat message quota and current usage.

        Args:
            data: User info JSON data.

        Returns:
            RateWindow with monthly usage percentage.
        """
        try:
            # Extract plan limits from Copilot response.
            plan = data.get("plan", {})
            plan_name = plan.get("name", "free")

            # Extract usage counters.
            usage = data.get("usage", {})
            chats_used = usage.get("chats_used", 0)
            chats_limit = usage.get("chats_limit", 0)

            # Some plans report usage as a percentage directly.
            if "usage_percent" in data:
                used_percent = min(data["usage_percent"] / 100.0, 2.0)
            elif chats_limit > 0:
                used_percent = min(chats_used / chats_limit, 2.0)
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
                reset_description=f"Copilot {plan_name} plan resets monthly",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Copilot usage: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from Copilot user data.

        Ported from: Sources/CodexBarCore/Providers/Copilot/CopilotProvider.swift:_parseIdentity()

        Args:
            data: User info JSON data.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            login = data.get("login")
            email = data.get("email")
            plan = data.get("plan", {}).get("name", "unknown")

            return ProviderIdentitySnapshot(
                account_email=email or f"{login}@github.com" if login else email,
                account_organization=plan,
                login_method="github_token",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Copilot identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get GitHub token from environment variables.

        Ported from: Sources/CodexBarCore/Providers/Copilot/CopilotProvider.swift:getApiKeyFromEnv()

        Checks:
        1. GITHUB_TOKEN (primary)
        2. GH_TOKEN (fallback)
        3. GitHub CLI token (~/.config/github-cli/state.json)

        Returns:
            GitHub token string or None.
        """
        # Direct environment variables.
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            return token

        # GitHub CLI token file.
        gh_cli_state = Path.home() / ".config" / "github-cli" / "state.json"
        if gh_cli_state.exists():
            try:
                import json
                state = json.loads(gh_cli_state.read_text())
                hosts = state.get("hosts", {})
                gh_token = hosts.get("github.com", {}).get("oauth_token")
                if gh_token:
                    return gh_token
            except (json.JSONDecodeError, OSError, AttributeError):
                pass

        return None

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/Copilot/CopilotProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "copilot",
            "name": "GitHub Copilot",
            "description": "GitHub Copilot Plan & Usage",
            "linux_support": "full",
            "auth_method": "bearer_token",
            "config_env_vars": ["GITHUB_TOKEN", "GH_TOKEN"],
            "dashboard_url": "https://github.com/settings/copilot",
            "status_url": "https://www.githubstatus.com",
        }
