"""HTTP client and data model for codexbar-usage provider snapshots."""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

logger = logging.getLogger("codexbar_gui.provider_model")


class UsageModel:
    """Fetches and caches provider usage data from the HTTP server."""

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url.rstrip("/")
        self.snapshots: List[Dict[str, Any]] = []
        self._last_error: Optional[str] = None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def fetch_all(self) -> List[Dict[str, Any]]:
        """Fetch all provider usage snapshots. Returns cached data on failure."""
        url = f"{self.server_url}/usage"
        try:
            data = self._get_json(url)
            if isinstance(data, list):
                self.snapshots = data
            elif isinstance(data, dict) and "results" in data:
                self.snapshots = data["results"]
            else:
                self.snapshots = []
            self._last_error = None
            logger.debug("Fetched %d snapshots", len(self.snapshots))
        except Exception as e:
            self._last_error = str(e)
            logger.warning("Failed to fetch usage from %s: %s", url, e)
        return self.snapshots

    def fetch_cost(self) -> List[Dict[str, Any]]:
        """Fetch cost data. Returns cached data on failure."""
        url = f"{self.server_url}/cost"
        try:
            data = self._get_json(url)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "results" in data:
                return data["results"]
            return []
        except Exception as e:
            logger.warning("Failed to fetch cost from %s: %s", url, e)
            return []

    def _get_json(self, url: str) -> Any:
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        logger.debug("GET %s", url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
        return json.loads(body)

    def health_check(self) -> bool:
        """Check if the server is reachable."""
        try:
            self._get_json(f"{self.server_url}/health")
            return True
        except Exception as e:
            logger.debug("Health check failed: %s", e)
            return False
