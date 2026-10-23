"""Fixed-window rate limiter backed by Redis, with an in-process fallback for dev/test."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Protocol

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.errors import RateLimitedError


class _Backend(Protocol):
    async def hit(self, key: str, window_seconds: int) -> int: ...


class _MemoryBackend:
    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)

    async def hit(self, key: str, window_seconds: int) -> int:
        bucket = f"{key}:{int(time.time() // window_seconds)}"
        self._counts[bucket] += 1
        if len(self._counts) > 10_000:
            self._counts.clear()
        return self._counts[bucket]


class _RedisBackend:
    def __init__(self, client: Redis) -> None:
        self._client = client

    async def hit(self, key: str, window_seconds: int) -> int:
        bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incr(bucket)
            pipe.expire(bucket, window_seconds)
            count, _ = await pipe.execute()
        return int(count)


_backend: _Backend | None = None


def _get_backend() -> _Backend:
    global _backend  # noqa: PLW0603
    if _backend is None:
        url = get_settings().redis_url
        _backend = _RedisBackend(Redis.from_url(url)) if url else _MemoryBackend()
    return _backend


def reset_rate_limiter() -> None:
    global _backend  # noqa: PLW0603
    _backend = None


async def enforce(key: str, limit: int, window_seconds: int = 60) -> None:
    count = await _get_backend().hit(key, window_seconds)
    if count > limit:
        raise RateLimitedError("Too many attempts. Please wait a minute and try again.")
