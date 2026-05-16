"""In-memory cache helpers for analytics_repo.

This module centralizes the cache data structure so other repos can
invalidate analytics results without creating import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, Optional, Tuple


@dataclass
class AnalyticsCache:
    enabled: bool = True

    def __post_init__(self) -> None:
        self._lock = RLock()
        # key -> value
        self._cache: Dict[Tuple[Any, ...], Any] = {}
        # Simple invalidation strategy: bump a version counter.
        # Cache entries include the version they were computed with.
        self._version: int = 0

    def make_key(self, *parts: Any) -> Tuple[Any, ...]:
        return ("v", self._version, *parts)

    def get(self, *parts: Any) -> Optional[Any]:
        if not self.enabled:
            return None
        k = self.make_key(*parts)
        with self._lock:
            return self._cache.get(k)

    def set(self, value: Any, *parts: Any) -> None:
        if not self.enabled:
            return
        k = self.make_key(*parts)
        with self._lock:
            self._cache[k] = value

    def invalidate(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._version += 1
            self._cache.clear()


_GLOBAL_CACHE = AnalyticsCache(enabled=True)


def get_cache() -> AnalyticsCache:
    return _GLOBAL_CACHE


def invalidate_analytics_cache() -> None:
    """Invalidate all analytics cached results."""
    _GLOBAL_CACHE.invalidate()

