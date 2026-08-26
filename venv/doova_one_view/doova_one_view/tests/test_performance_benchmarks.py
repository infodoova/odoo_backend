# doova_one_view/tests/test_performance_benchmarks.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
import time
from unittest.mock import patch
from doova_one_view.api.agent.tools_refactored.sales import get_sales_summary_tool
from doova_one_view.api.agent.tools_refactored.common import normalize_business_text_for_intent

class TestPerformanceBenchmarks(unittest.TestCase):

    def test_text_normalization_benchmark(self):
        """Benchmark intent normalizer latency across 10,000 operations (SLA < 200ms total)."""
        sample_text = "Check revnue, salse, inventry, and stok for prodcut A"
        start = time.perf_counter()
        for _ in range(10000):
            normalize_business_text_for_intent(sample_text)
        duration_ms = (time.perf_counter() - start) * 1000
        
        self.assertLess(
            duration_ms, 200.0,
            f"Performance Bottleneck: Text normalization took {duration_ms:.2f}ms (threshold: 200ms)"
        )

    @patch("doova_one_view.api.agent.tools_refactored.sales.run_query")
    def test_tool_execution_benchmark(self, mock_run_query):
        """Benchmark tool execution wrapper latency (SLA < 15ms per call excluding DB network)."""
        mock_run_query.return_value = [{"total_revenue": 100000.0, "order_count": 10, "average_order_value": 10000.0}]
        
        start = time.perf_counter()
        for _ in range(100):
            get_sales_summary_tool(tenant_id="default")
        duration_ms = (time.perf_counter() - start) * 1000
        avg_ms = duration_ms / 100

        self.assertLess(
            avg_ms, 15.0,
            f"Performance Overhead: Tool wrapper took average {avg_ms:.2f}ms (threshold: 15.0ms)"
        )

if __name__ == "__main__":
    unittest.main()
