"""Sliding-window rate limiting with Redis and an in-process fallback.

The limiter protects link creation and authentication endpoints from abuse.
Redis is used when configured; otherwise a per-process window keeps the
service usable for local development and tests.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import client_ip, hash_ip

logger = logging.getLogger("app.rate_limit")

#: Redis key namespace.
KEY_PREFIX = "ratelimit:"


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a single limiter check."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int

    def headers(self) -> dict[str, str]:
        """Return standard ``X-RateLimit-*`` response headers."""
        data = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
        }
        if not self.allowed:
            data["Retry-After"] = str(max(1, self.retry_after))
        return data


class RateLimiter:
    """A small sliding-window limiter with an optional Redis backend."""

    def __init__(self) -> None:
        """Create an empty limiter; connections are opened lazily."""
        self._lock = threading.Lock()
        self._memory: dict[str, deque[float]] = defaultdict(deque)
        self._redis = None
        self._redis_checked = False

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------
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
                logger.warning("Redis unavailable for rate limiting: %s", exc)
                self._redis = None
        return self._redis

    @property
    def backend(self) -> str:
        """Return the active backend name."""
        return "redis" if self._redis_client() is not None else "memory"

    # ------------------------------------------------------------------
    # Check
    # ------------------------------------------------------------------
    def hit(self, key: str, limit: int, window_seconds: int = 60) -> RateLimitResult:
        """Register one hit and report whether the caller stays under ``limit``."""
        limit = max(1, int(limit))
        window = max(1, int(window_seconds))
        client = self._redis_client()
        if client is not None:
            try:
                return self._hit_redis(client, key, limit, window)
            except Exception as exc:  # pragma: no cover - depends on infrastructure
                logger.warning("Redis rate-limit call failed, using memory: %s", exc)
        return self._hit_memory(key, limit, window)

    def _hit_memory(self, key: str, limit: int, window: int) -> RateLimitResult:
        """Apply the sliding window inside the current process."""
        now = time.monotonic()
        with self._lock:
            window_hits = self._memory[key]
            while window_hits and now - window_hits[0] > window:
                window_hits.popleft()
            if len(window_hits) >= limit:
                retry_after = max(1, int(window - (now - window_hits[0])) + 1)
                return RateLimitResult(False, limit, 0, retry_after)
            window_hits.append(now)
            return RateLimitResult(True, limit, limit - len(window_hits), 0)

    def _hit_redis(self, client, key: str, limit: int, window: int) -> RateLimitResult:
        """Apply the sliding window in Redis using a sorted set per key."""
        redis_key = f"{KEY_PREFIX}{key}"
        now = time.time()
        pipe = client.pipeline()
        pipe.zremrangebyscore(redis_key, 0, now - window)
        pipe.zadd(redis_key, {f"{now}:{time.perf_counter_ns()}": now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window + 1)
        results = pipe.execute()
        used = int(results[2])
        if used > limit:
            client.zremrangebyscore(redis_key, now - window, now)
            return RateLimitResult(False, limit, 0, window)
        return RateLimitResult(True, limit, max(0, limit - used), 0)

    def reset(self) -> None:
        """Forget every in-process counter (used by tests)."""
        with self._lock:
            self._memory.clear()


#: Process-wide limiter shared by all routes.
limiter = RateLimiter()


def enforce_rate_limit(request: Request, bucket: str, limit: int) -> RateLimitResult:
    """Apply ``limit`` requests per minute per visitor and raise on overflow."""
    fingerprint = hash_ip(client_ip(request))
    result = limiter.hit(f"{bucket}:{fingerprint}", limit, 60)
    if not result.allowed:
        raise AppError(
            429,
            "rate_limited",
            f"Too many requests. Try again in {result.retry_after} seconds.",
            details={"retry_after": result.retry_after},
            headers=result.headers(),
        )
    request.state.rate_limit = result
    return result


def enforce_create_limit(request: Request) -> RateLimitResult:
    """Rate-limit short-link creation per visitor."""
    return enforce_rate_limit(request, "create", settings.rate_limit_create_per_minute)


def enforce_auth_limit(request: Request) -> RateLimitResult:
    """Rate-limit authentication attempts per visitor."""
    return enforce_rate_limit(request, "auth", settings.rate_limit_auth_per_minute)
