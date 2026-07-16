"""Cheap JSON ETag + short TTL snapshot cache for portal APIs."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Callable


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )


def etag_for_body(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:16] + '"'


class TtlCache:
    """Thread-safe TTL cache for expensive snapshot builders."""

    def __init__(self, ttl_s: float = 3.0) -> None:
        self.ttl_s = ttl_s
        self._lock = threading.Lock()
        self._value: Any = None
        self._at = 0.0
        self._body: bytes | None = None
        self._etag: str | None = None

    def get_or_build(self, builder: Callable[[], Any]) -> tuple[Any, bytes, str]:
        now = time.monotonic()
        with self._lock:
            if self._body is not None and (now - self._at) < self.ttl_s:
                return self._value, self._body, self._etag or etag_for_body(self._body)
        value = builder()
        body = json_bytes(value)
        tag = etag_for_body(body)
        with self._lock:
            self._value = value
            self._body = body
            self._etag = tag
            self._at = time.monotonic()
        return value, body, tag
