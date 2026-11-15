"""A tiny cache for resolved links.

Redis is optional: when it is absent the service keeps an in-process
dictionary with per-entry expiry.  Cached entries are plain dictionaries so
the redirect path never needs to touch the database for a warm code.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger("app.cache")

#: Redis key namespace for link entries.
KEY_PREFIX = "link:"


class LinkCache:
    """Cache resolved link payloads by short code."""

    def __init__(self) -> None:
        """Create an empty cache; the Redis client is opened lazily."""
        self._lock = threading.Lock()
        self._memory: dict[str, tuple[float, dict[str, Any]]] = {}
        self._redis = None
        self._redis_checked = False

    def _redis_client(self):
        """Return a Redis client or ``None`` when Redis is unavailable."""
        if not settings.redis_url:
            return None
        if not self._redis_checked:
            self._redis_checked = True
            try:
                import redis

                self._redis = redis.from_url(
                    settings.redis_url,
                    socket_connect_timeout=0.25,
                    socket_timeout=0.25,
                    decode_responses=True,
                )
                self._redis.ping()
            except Exception as exc:  # pragma: no cover - depends on infrastructure
                logger.warning("Redis unavailable for caching: %s", exc)
                self._redis = None
        return self._redis

    @property
    def backend(self) -> str:
        """Return the active backend name."""
        return "redis" if self._redis_client() is not None else "memory"

    def get(self, code: str) -> dict[str, Any] | None:
        """Return a cached payload or ``None``."""
        client = self._redis_client()
        if client is not None:
            try:
                raw = client.get(f"{KEY_PREFIX}{code}")
                if raw:
                    return json.loads(raw)
                return None
            except Exception as exc:  # pragma: no cover - depends on infrastructure
                logger.warning("Redis cache read failed: %s", exc)
        with self._lock:
            entry = self._memory.get(code)
            if entry is None:
                return None
            expires_at, payload = entry
            if expires_at <= time.monotonic():
                self._memory.pop(code, None)
                return None
            return dict(payload)

    def set(self, code: str, payload: dict[str, Any], ttl_seconds: int | None = None) -> None:
        """Store a payload for a limited time."""
        ttl = settings.cache_ttl_seconds if ttl_seconds is None else int(ttl_seconds)
        if ttl <= 0:
            return
        client = self._redis_client()
        if client is not None:
            try:
                client.setex(f"{KEY_PREFIX}{code}", ttl, json.dumps(payload))
                return
            except Exception as exc:  # pragma: no cover - depends on infrastructure
                logger.warning("Redis cache write failed: %s", exc)
        with self._lock:
            self._memory[code] = (time.monotonic() + ttl, dict(payload))

    def delete(self, code: str) -> None:
        """Drop a cached payload after a link changes."""
        client = self._redis_client()
        if client is not None:
            try:
                client.delete(f"{KEY_PREFIX}{code}")
            except Exception as exc:  # pragma: no cover - depends on infrastructure
                logger.warning("Redis cache delete failed: %s", exc)
        with self._lock:
            self._memory.pop(code, None)

    def clear(self) -> None:
        """Forget every in-process entry (used by tests)."""
        with self._lock:
            self._memory.clear()


#: Process-wide link cache.
link_cache = LinkCache()
