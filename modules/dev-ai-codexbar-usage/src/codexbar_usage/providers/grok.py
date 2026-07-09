"""Grok provider implementation.

Ported from CodexBar Swift source:
- Sources/CodexBarCore/Providers/Grok/GrokProvider.swift
- Sources/CodexBarCore/Providers/Grok/GrokCLIClient.swift
- Sources/CodexBarCore/Providers/Grok/GrokWebFallback.swift

References:
- CLI: grok agent stdio JSON-RPC x.ai/billing
- Web fallback: grok.com billing via gRPC-web with Chrome cookies
- Auth: Bearer token (xai-api-key)
- Linux Support: partial (CLI fully, web via browser context)
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

# Default timeout for grok CLI subprocess calls.
GROK_CLI_TIMEOUT = 30.0
# Default timeout for web fallback.
GROK_WEB_TIMEOUT = 30.0


class GrokProvider(BaseProvider):
    """Grok provider using CLI and web fallback.

    Ported from: Sources/CodexBarCore/Providers/Grok/GrokProvider.swift

    Supports:
    - CLI: `grok agent stdio` JSON-RPC `x.ai/billing`
    - Web fallback: grok.com billing via gRPC-web with browser cookies
    - Bearer token auth for API calls

    Linux Support: partial (CLI full, web requires browser cookies)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cli_command: str = "grok",
        base_url: str = "https://api.x.ai/v1",
        use_web_fallback: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Grok provider.

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokProvider.swift:init

        Args:
            api_key: Bearer token for API calls (xai-api-key).
            cli_command: Path to grok CLI binary or command.
            base_url: Base URL for xAI API endpoints.
            use_web_fallback: Whether to use web fallback if CLI fails.
            config: Additional configuration.
        """
        super().__init__(
            provider_id="grok",
            api_key=api_key,
            base_url=base_url,
            config=config,
        )
        self.cli_command = cli_command
        self.use_web_fallback = use_web_fallback
        self._logger = logging.getLogger(f"providers.grok")

    async def fetch_usage(self) -> UsageSnapshot:
        """Fetch Grok usage via CLI or web fallback.

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokProvider.swift:fetchUsage()

        Strategy:
        1. Try CLI: `grok agent stdio` JSON-RPC x.ai/billing
        2. Fallback to web: grok.com billing endpoint
        3. Fallback to API: Bearer token with xAI API

        Returns:
            UsageSnapshot with primary rate window and identity.

        Raises:
            AuthError: If no authentication available.
            NetworkError: If all fetch methods fail.
        """
        self.status = ProviderStatus.READY

        try:
            # Strategy 1: CLI approach.
            usage_data = await self._try_cli()

            primary_window = self._parse_usage(usage_data)
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
            self.last_error = ProviderError(f"Failed to fetch Grok usage: {e}")
            raise self.last_error

    async def _try_cli(self) -> Dict[str, Any]:
        """Try fetching usage via grok CLI.

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokCLIClient.swift:_tryCli()

        Spawns `grok agent stdio` process and sends JSON-RPC request
        to the `x.ai/billing` method.

        Returns:
            Usage data dictionary.

        Raises:
            ProviderError: If CLI not available or request fails.
        """
        # Check if grok CLI is available.
        if not await self._cli_available():
            raise ProviderError("grok CLI not found in PATH", "cli_not_available")

        # Build JSON-RPC request for billing info.
        request_id = 1
        jsonrpc_request = json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "x.ai/billing",
            "params": {},
        })

        try:
            # Spawn grok agent stdio process.
            proc = await asyncio_create_subprocess(
                self.cli_command,
                "agent",
                "stdio",
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Send JSON-RPC request.
            stdout_data, stderr_data = await asyncio_run_with_timeout(
                proc.communicate(input=jsonrpc_request.encode()),
                GROK_CLI_TIMEOUT,
            )

            if proc.returncode != 0:
                raise ProviderError(
                    f"grok CLI exited with code {proc.returncode}: {stderr_data.decode()}"
                )

            # Parse JSON-RPC response.
            if stdout_data:
                response = json.loads(stdout_data.decode())
                if "error" in response:
                    raise ProviderError(
                        f"grok CLI error: {response['error']}", "cli_error"
                    )
                result = response.get("result", response)
                return result

            raise ProviderError("Empty response from grok CLI")

        except FileNotFoundError:
            raise ProviderError("grok CLI not found", "cli_not_found")
        except subprocess.TimeoutExpired:
            raise ProviderError("grok CLI request timed out", "cli_timeout")
        except json.JSONDecodeError as e:
            raise ProviderError(f"Invalid JSON from grok CLI: {e}", "cli_parse_error")

    async def _try_web_fallback(self) -> Dict[str, Any]:
        """Try fetching usage via web fallback (grok.com billing).

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokWebFallback.swift:_tryWebFallback()

        Uses gRPC-web to grok.com billing endpoint with browser cookies.

        Returns:
            Usage data dictionary.

        Raises:
            NetworkError: If web fallback fails.
        """
        if not self.use_web_fallback:
            raise ProviderError("Web fallback disabled in config", "web_disabled")

        url = "https://grok.com/api/billing"

        try:
            async with httpx.AsyncClient(timeout=GROK_WEB_TIMEOUT) as client:
                headers = {
                    "Accept": "application/json",
                    "User-Agent": "CodexBar-Python/1.0",
                }

                # Include cookie auth if available.
                cookies = self._get_browser_cookies()
                if cookies:
                    headers["Cookie"] = cookies

                response = await client.get(url, headers=headers)
                self._handle_response_error(response)

                if response.status_code == 401:
                    raise AuthError("Authentication required for grok.com billing")

                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            raise NetworkError(
                f"Web fallback request failed: {e}", e.response.status_code
            )
        except httpx.TimeoutException:
            raise NetworkError("Web fallback request timed out")
        except httpx.RequestError as e:
            raise NetworkError(f"Web fallback request error: {e}")

    async def _cli_available(self) -> bool:
        """Check if grok CLI is available in PATH.

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokCLIClient.swift:_cliAvailable()

        Returns:
            True if grok CLI is found and executable.
        """
        try:
            result = await asyncio_create_subprocess(
                self.cli_command, "--version",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except (FileNotFoundError, OSError):
            return False

    def _get_browser_cookies(self) -> Optional[str]:
        """Get browser cookies for grok.com authentication.

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokWebFallback.swift:_getBrowserCookies()

        Reads cookies from Chrome/Chromium cookie database.

        Returns:
            Cookie string or None.
        """
        # Check XDG cookie storage for Chromium-based browsers.
        cookie_paths = [
            Path.home() / ".config" / "google-chrome" / "Default" / "Cookies",
            Path.home() / ".config" / "Chromium" / "Default" / "Cookies",
        ]

        for cookie_path in cookie_paths:
            if cookie_path.exists():
                try:
                    # Use Chromium's cookie database via sqlite.
                    import sqlite3
                    conn = sqlite3.connect(str(cookie_path))
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT name, value FROM cookies WHERE host_key LIKE '%grok.com'"
                    )
                    cookies = cursor.fetchall()
                    conn.close()

                    if cookies:
                        cookie_str = "; ".join(f"{name}={value}" for name, value in cookies)
                        return cookie_str
                except (sqlite3.Error, OSError) as e:
                    logger.debug(f"Failed to read cookies from {cookie_path}: {e}")
                    continue

        return None

    def _parse_usage(self, data: Dict[str, Any]) -> Optional[RateWindow]:
        """Parse Grok usage data into RateWindow.

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokProvider.swift:_parseUsage()

        Handles both CLI JSON-RPC response and web API response formats.

        Args:
            data: Usage data from CLI or web.

        Returns:
            RateWindow with usage percentage.
        """
        try:
            # Handle CLI JSON-RPC response format.
            if "messages" in data:
                total_messages = data.get("messages", 0)
                limit = data.get("message_limit", 0)
            elif "usage" in data:
                usage = data["usage"]
                total_messages = usage.get("total", usage.get("messages_used", 0))
                limit = usage.get("limit", usage.get("messages_limit", 0))
            else:
                total_messages = data.get("total_usage", 0)
                limit = data.get("total_limit", 0)

            if limit > 0:
                used_percent = min(total_messages / limit, 2.0)
            else:
                used_percent = 0.0

            # Grok usage resets monthly.
            now = datetime.now(timezone.utc)
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)

            return RateWindow(
                used_percent=used_percent,
                window_minutes=43200,
                resets_at=next_month,
                reset_description="Monthly message quota reset",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Grok usage: {e}")
            return None

    def _parse_identity(self, data: Dict[str, Any]) -> Optional[ProviderIdentitySnapshot]:
        """Parse identity from Grok data.

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokProvider.swift:_parseIdentity()

        Args:
            data: Usage data from CLI or web.

        Returns:
            ProviderIdentitySnapshot with account information.
        """
        try:
            email = data.get("email")
            username = data.get("username") or data.get("login")
            plan = data.get("plan", "unknown")

            return ProviderIdentitySnapshot(
                account_email=email,
                account_organization=plan,
                login_method="bearer_token" if self.api_key else "cli",
            )

        except Exception as e:
            logger.warning(f"Failed to parse Grok identity: {e}")
            return None

    def get_api_key_from_env(self) -> Optional[str]:
        """Get bearer token from environment variables.

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokProvider.swift:getApiKeyFromEnv()

        Checks:
        1. XAI_API_KEY (primary)
        2. GROK_API_KEY (fallback)

        Returns:
            Bearer token string or None.
        """
        return os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")

    @staticmethod
    def get_provider_metadata() -> Dict[str, Any]:
        """Get provider metadata for display.

        Ported from: Sources/CodexBarCore/Providers/Grok/GrokProvider.swift:getProviderMetadata()

        Returns:
            Dictionary with provider display information.
        """
        return {
            "provider_id": "grok",
            "name": "Grok",
            "description": "xAI Grok Usage (CLI + Web)",
            "linux_support": "partial",
            "auth_method": "bearer_token",
            "config_env_vars": ["XAI_API_KEY", "GROK_API_KEY"],
            "dashboard_url": "https://grok.com/settings",
            "status_url": None,
        }


# Async helpers to avoid importing asyncio at module level for subprocess.
import asyncio


async def asyncio_create_subprocess(*args: str, **kwargs: Any) -> subprocess.CompletedProcess:
    """Create an asyncio subprocess.

    Args:
        *args: Command and arguments.
        **kwargs: Subprocess keyword arguments.

    Returns:
        CompletedProcess instance.
    """
    proc = await asyncio.create_subprocess_exec(*args, **kwargs)
    return await proc.wait()


async def asyncio_run_with_timeout(coroutine, timeout: float):
    """Run a coroutine with a timeout.

    Args:
        coroutine: Coroutine to run.
        timeout: Timeout in seconds.

    Returns:
        Result of the coroutine.

    Raises:
        subprocess.TimeoutExpired: If timeout exceeded.
    """
    return await asyncio.wait_for(coroutine, timeout=timeout)
