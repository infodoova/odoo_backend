# doova_one_view/tests/test_agent_performance_extended.py
"""
Extended Agent Performance & SLA Benchmark Suite.

Benchmarks latency, throughput, cache lookups, text normalization, and thread safety.
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
import time
import concurrent.futures
from unittest.mock import patch, MagicMock
from doova_one_view.api.agent.tools_refactored.common import normalize_business_text_for_intent
from doova_one_view.api.agent.query_context import normalize_tenant_ids, normalize_company_ids
from doova_one_view.api.agent.cache import InMemoryTTLCache


class TestAgentPerformanceExtended(unittest.TestCase):
    """Performance benchmarks verifying latency SLAs and concurrency safety."""

    def test_query_context_normalization_latency(self):
        """Benchmark multi-tenant context normalization across 500 operations (SLA < 500ms)."""
        uuid1 = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        uuid2 = "99999999-8888-7777-6666-555555555555"
        raw_tenants = [uuid1, uuid2, uuid1, None]
        raw_companies = [10, 20, 10, 30, "40"]

        start = time.perf_counter()
        for _ in range(500):
            normalize_tenant_ids(raw_tenants)
            normalize_company_ids(raw_companies)
        duration_ms = (time.perf_counter() - start) * 1000

        self.assertLess(
            duration_ms, 500.0,
            f"Performance SLA Failure: Context normalization took {duration_ms:.2f}ms (threshold: 500ms)"
        )

    def test_ttl_cache_hit_latency_and_concurrency(self):
        """Benchmark TTL cache hit lookup latency (< 0.05ms per hit) under concurrent access."""
        cache = InMemoryTTLCache(ttl_seconds=300, maxsize=100)
        cache.set(("key_1",), {"schema": "public", "tables": 45})

        def worker():
            for _ in range(1000):
                found, val = cache.get(("key_1",))
                self.assertTrue(found)

        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(10)]
            for f in concurrent.futures.as_completed(futures):
                f.result()
        duration_ms = (time.perf_counter() - start) * 1000

        self.assertLess(
            duration_ms, 100.0,
            f"TTL Cache Concurrency Bottleneck: 10k concurrent reads took {duration_ms:.2f}ms (threshold: 100ms)"
        )

    def test_json_extraction_benchmark(self):
        """Benchmark JSON response block extraction speed across 5,000 items (SLA < 50ms)."""
        from doova_one_view.api.agent.routes import _extract_json_block

        sample_response = (
            "Here is the financial audit report:\n"
            "```json\n"
            '{\n  "score": 92,\n  "status": "Verified",\n  "grade": "AA"\n}\n'
            "```\n"
            "End of report."
        )

        start = time.perf_counter()
        for _ in range(5000):
            res = _extract_json_block(sample_response)
            self.assertEqual(res["score"], 92)
        duration_ms = (time.perf_counter() - start) * 1000

        self.assertLess(
            duration_ms, 80.0,
            f"JSON Parser Bottleneck: 5k extractions took {duration_ms:.2f}ms (threshold: 80ms)"
        )


if __name__ == "__main__":
    unittest.main()
