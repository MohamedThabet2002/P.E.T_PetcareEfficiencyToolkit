"""Tests for src/core/repositories/analytics_cache.py"""

import pytest

from src.core.repositories.analytics_cache import (
    AnalyticsCache,
    get_cache,
    invalidate_analytics_cache,
)


class TestAnalyticsCacheInstance:
    def test_get_miss_returns_none(self):
        cache = AnalyticsCache()
        assert cache.get("missing") is None

    def test_set_then_get(self):
        cache = AnalyticsCache()
        cache.set({"result": 1}, "kpi", "All")
        assert cache.get("kpi", "All") == {"result": 1}

    def test_get_with_wrong_key_returns_none(self):
        cache = AnalyticsCache()
        cache.set(42, "kpi", "All")
        assert cache.get("kpi", "Week") is None
        assert cache.get("other", "All") is None

    def test_get_after_invalidate_returns_none(self):
        cache = AnalyticsCache()
        cache.set(10, "key")
        cache.invalidate()
        assert cache.get("key") is None

    def test_set_after_invalidate_does_not_conflict(self):
        cache = AnalyticsCache()
        cache.set(10, "key")
        cache.invalidate()
        cache.set(20, "key")
        assert cache.get("key") == 20

    def test_invalidate_clears_all(self):
        cache = AnalyticsCache()
        cache.set(1, "a")
        cache.set(2, "b", "c")
        cache.invalidate()
        assert cache.get("a") is None
        assert cache.get("b", "c") is None

    def test_multiple_unique_caches_are_independent(self):
        c1 = AnalyticsCache()
        c2 = AnalyticsCache()
        c1.set("v1", "key")
        assert c2.get("key") is None


class TestAnalyticsCacheDisabled:
    def test_disabled_get_returns_none(self):
        cache = AnalyticsCache(enabled=False)
        cache.set(5, "key")
        assert cache.get("key") is None

    def test_disabled_set_stores_nothing(self):
        cache = AnalyticsCache(enabled=False)
        cache.set(5, "key")
        cache.invalidate()  # no-op, must not raise
        assert cache.get("key") is None


class TestGlobalCache:
    def test_get_cache_singleton(self):
        assert get_cache() is get_cache()

    def test_invalidate_analytics_cache_bumps_version(self):
        cache = get_cache()
        cache.set("value", "some_entity")
        invalidate_analytics_cache()
        assert cache.get("some_entity") is None
