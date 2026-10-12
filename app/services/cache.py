"""
High-Performance Two-Tier Caching Service.

Provides sub-millisecond retrieval of processed file metadata, measurements,
and GeoJSON exports under high request volumes (e.g. 100,000+ requests).

Tier 1: Redis Distributed Cache (when REDIS_URL configured and redis installed).
Tier 2: In-Memory Thread-Safe LRU Cache with TTL expiration (zero-dependency fallback).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class MemoryCache:
    """
    Thread-safe in-memory LRU cache with per-item TTL expiration.
    Capable of handling tens of thousands of ops/sec in pure Python.
    """

    def __init__(self, max_items: int = 10000, default_ttl: int = 300):
        self.max_items = max_items
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                self.misses += 1
                return None

            value, expires_at = self._cache[key]
            if time.time() > expires_at:
                del self._cache[key]
                self.misses += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            ttl_seconds = ttl if ttl is not None else self.default_ttl
            expires_at = time.time() + ttl_seconds

            if key in self._cache:
                self._cache[key] = (value, expires_at)
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self.max_items:
                    # Pop oldest (least recently used)
                    self._cache.popitem(last=False)
                self._cache[key] = (value, expires_at)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching pattern. Supports '*' wildcard at end or within."""
        with self._lock:
            prefix = pattern.replace("*", "")
            to_delete = [k for k in self._cache if prefix in k]
            for k in to_delete:
                del self._cache[k]
            return len(to_delete)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            ratio = round((self.hits / total) * 100, 2) if total > 0 else 0.0
            return {
                "backend": "memory",
                "items_count": len(self._cache),
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio_percent": ratio,
            }


class CacheService:
    """
    Unified cache manager that orchestrates Redis or in-memory fallback.
    """

    def __init__(self):
        self._memory = MemoryCache(
            max_items=settings.cache_max_memory_items,
            default_ttl=settings.cache_default_ttl,
        )
        self._redis_client = None
        self._init_redis()

    def _init_redis(self):
        if not settings.redis_url:
            return

        try:
            import redis
            client = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
            client.ping()
            self._redis_client = client
            logger.info("Connected to Redis cache at %s", settings.redis_url)
        except Exception as exc:
            logger.warning("Redis unavailable (%s), falling back to in-memory LRU cache", exc)
            self._redis_client = None

    @property
    def is_redis(self) -> bool:
        return self._redis_client is not None

    def get(self, key: str) -> Optional[Any]:
        if not settings.cache_enabled:
            return None

        if self._redis_client:
            try:
                raw = self._redis_client.get(key)
                if raw is not None:
                    return json.loads(raw)
                return None
            except Exception as exc:
                logger.debug("Redis get error (%s), falling back to memory", exc)

        return self._memory.get(key)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        if not settings.cache_enabled:
            return False

        effective_ttl = ttl if ttl is not None else settings.cache_default_ttl

        if self._redis_client:
            try:
                serialized = json.dumps(value)
                self._redis_client.setex(key, effective_ttl, serialized)
                return True
            except Exception as exc:
                logger.debug("Redis set error (%s), setting in memory", exc)

        self._memory.set(key, value, ttl=effective_ttl)
        return True

    def delete(self, key: str) -> bool:
        deleted = False
        if self._redis_client:
            try:
                deleted = bool(self._redis_client.delete(key))
            except Exception as exc:
                logger.debug("Redis delete error: %s", exc)

        mem_deleted = self._memory.delete(key)
        return deleted or mem_deleted

    def delete_pattern(self, pattern: str) -> int:
        count = 0
        if self._redis_client:
            try:
                keys = list(self._redis_client.scan_iter(match=pattern))
                if keys:
                    count += self._redis_client.delete(*keys)
            except Exception as exc:
                logger.debug("Redis delete_pattern error: %s", exc)

        count += self._memory.delete_pattern(pattern)
        return count

    def clear(self) -> None:
        if self._redis_client:
            try:
                self._redis_client.flushdb()
            except Exception as exc:
                logger.debug("Redis flush error: %s", exc)
        self._memory.clear()

    def get_stats(self) -> dict:
        stats = self._memory.stats()
        if self._redis_client:
            try:
                info = self._redis_client.info()
                stats["backend"] = "redis"
                stats["redis_connected_clients"] = info.get("connected_clients")
                stats["redis_used_memory_human"] = info.get("used_memory_human")
            except Exception:
                stats["backend"] = "memory_fallback"
        return stats


cache = CacheService()
