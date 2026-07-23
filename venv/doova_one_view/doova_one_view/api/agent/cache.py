"""
In-process thread-safe TTL Cache for Nexus Agent.

Provides zero-dependency, high-performance in-memory caching with TTL (Time-To-Live)
expiration, LRU eviction on overflow, manual invalidation by cache name, and statistics reporting.
"""

import time
import functools
import threading
from typing import Any, Callable, Dict, Tuple, Optional


class TTLCacheRegistry:
    """Central registry tracking all TTL caches for management, stats, and invalidation."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._caches: Dict[str, "InMemoryTTLCache"] = {}
            return cls._instance

    def register(self, name: str, cache: "InMemoryTTLCache"):
        with self._lock:
            self._caches[name] = cache

    def clear(self, name: Optional[str] = None):
        with self._lock:
            if name:
                if name in self._caches:
                    self._caches[name].clear()
            else:
                for cache in self._caches.values():
                    cache.clear()

    def get_stats(self) -> Dict[str, dict]:
        with self._lock:
            return {
                name: cache.stats()
                for name, cache in self._caches.items()
            }


class InMemoryTTLCache:
    """Thread-safe dictionary-backed cache entry with TTL and capacity limits."""

    def __init__(self, ttl_seconds: float, maxsize: int = 128, name: str = "default"):
        self.ttl_seconds = ttl_seconds
        self.maxsize = maxsize
        self.name = name
        self._store: Dict[Tuple, Tuple[Any, float]] = {}  # key -> (value, expiry_timestamp)
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def get(self, key: Tuple) -> Tuple[bool, Any]:
        with self._lock:
            now = time.time()
            if key in self._store:
                val, expiry = self._store[key]
                if now < expiry:
                    self._hits += 1
                    return True, val
                else:
                    # Expired
                    del self._store[key]
            self._misses += 1
            return False, None

    def set(self, key: Tuple, value: Any):
        with self._lock:
            now = time.time()
            # If maxsize reached, prune expired or oldest
            if len(self._store) >= self.maxsize and key not in self._store:
                self._prune(now)
                if len(self._store) >= self.maxsize:
                    # Evict first key
                    first_key = next(iter(self._store))
                    del self._store[first_key]

            self._store[key] = (value, now + self.ttl_seconds)

    def _prune(self, now: float):
        expired = [k for k, (_, exp) in self._store.items() if now >= exp]
        for k in expired:
            del self._store[k]

    def clear(self):
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        with self._lock:
            now = time.time()
            active_items = sum(1 for _, exp in self._store.values() if now < exp)
            total_requests = self._hits + self._misses
            hit_ratio = round(self._hits / total_requests, 4) if total_requests > 0 else 0.0
            return {
                "name": self.name,
                "ttl_seconds": self.ttl_seconds,
                "maxsize": self.maxsize,
                "size": active_items,
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": hit_ratio,
            }


def ttl_cache(ttl_seconds: float, maxsize: int = 128, name: Optional[str] = None):
    """
    Decorator for caching function outputs based on arguments with a time-to-live.
    
    Usage:
        @ttl_cache(ttl_seconds=300, name="balance_sheet")
        def get_balance_sheet_tool(tenant_id, company_id=None):
            ...
    """
    def decorator(func: Callable) -> Callable:
        cache_name = name or func.__name__
        cache_obj = InMemoryTTLCache(ttl_seconds=ttl_seconds, maxsize=maxsize, name=cache_name)
        TTLCacheRegistry().register(cache_name, cache_obj)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create hashable key from args and kwargs
            key_args = tuple(_make_hashable(a) for a in args)
            key_kwargs = tuple(sorted((k, _make_hashable(v)) for k, v in kwargs.items()))
            cache_key = (key_args, key_kwargs)

            found, cached_val = cache_obj.get(cache_key)
            if found:
                return cached_val

            result = func(*args, **kwargs)
            cache_obj.set(cache_key, result)
            return result

        wrapper.cache_info = cache_obj.stats
        wrapper.cache_clear = cache_obj.clear
        return wrapper

    return decorator


def _make_hashable(val: Any) -> Any:
    """Helper to turn lists or dicts in tool parameters into hashable tuple structures."""
    if isinstance(val, list):
        return tuple(_make_hashable(x) for x in val)
    if isinstance(val, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in val.items()))
    if isinstance(val, set):
        return frozenset(_make_hashable(x) for x in val)
    return val


def invalidate_cache(name: Optional[str] = None):
    """Invalidate specific cache by name or all caches if name is None."""
    TTLCacheRegistry().clear(name)


def get_cache_stats() -> Dict[str, dict]:
    """Retrieve runtime performance statistics for all active TTL caches."""
    return TTLCacheRegistry().get_stats()
