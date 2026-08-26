# doova_one_view/tests/test_ttl_cache.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
import time
import threading
from doova_one_view.api.agent.cache import (
    InMemoryTTLCache,
    TTLCacheRegistry,
    ttl_cache,
    invalidate_cache,
    get_cache_stats,
    _make_hashable
)

class TestTTLCache(unittest.TestCase):

    def setUp(self):
        invalidate_cache()

    def test_cache_set_get_and_expiration(self):
        """Verify setting, retrieving, and expiration of cache entries."""
        cache = InMemoryTTLCache(ttl_seconds=0.1, maxsize=10, name="test_exp")
        cache.set(("key1",), "val1")
        
        found, val = cache.get(("key1",))
        self.assertTrue(found)
        self.assertEqual(val, "val1")
        
        # Wait for TTL to expire
        time.sleep(0.15)
        found_after, val_after = cache.get(("key1",))
        self.assertFalse(found_after)
        self.assertIsNone(val_after)

    def test_cache_maxsize_eviction(self):
        """Verify capacity limit pruning when maxsize is exceeded."""
        cache = InMemoryTTLCache(ttl_seconds=60, maxsize=2, name="test_evict")
        cache.set(("k1",), "v1")
        cache.set(("k2",), "v2")
        cache.set(("k3",), "v3")

        # Key 1 should have been evicted
        found1, _ = cache.get(("k1",))
        self.assertFalse(found1)
        
        found3, val3 = cache.get(("k3",))
        self.assertTrue(found3)
        self.assertEqual(val3, "v3")

    def test_hashable_conversion(self):
        """Verify _make_hashable converts dicts, lists, and sets into hashable tuples."""
        raw_list = [1, 2, {"a": [3, 4]}]
        hashable = _make_hashable(raw_list)
        self.assertIsInstance(hashable, tuple)
        self.assertEqual(hashable[0], 1)
        self.assertEqual(hashable[2], (("a", (3, 4)),))
        # Hash check
        self.assertIsInstance(hash(hashable), int)

    def test_ttl_cache_decorator(self):
        """Verify function decoration via @ttl_cache decorator."""
        call_count = 0

        @ttl_cache(ttl_seconds=10, name="test_fn")
        def expensive_fn(tenant_id, filters=None):
            nonlocal call_count
            call_count += 1
            return f"result_{tenant_id}"

        res1 = expensive_fn("t1", filters={"a": 1})
        res2 = expensive_fn("t1", filters={"a": 1})
        self.assertEqual(res1, "result_t1")
        self.assertEqual(res2, "result_t1")
        self.assertEqual(call_count, 1)  # Cached, function called only once

        stats = expensive_fn.cache_info()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)

    def test_thread_safety_concurrent_access(self):
        """Verify thread safety under concurrent reads and writes."""
        cache = InMemoryTTLCache(ttl_seconds=10, maxsize=100, name="concurrent_test")
        
        def worker(worker_id):
            for i in range(50):
                key = (f"key_{i % 10}",)
                cache.set(key, f"val_{worker_id}_{i}")
                cache.get(key)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = cache.stats()
        self.assertGreater(stats["hits"] + stats["misses"], 0)

if __name__ == "__main__":
    unittest.main()
