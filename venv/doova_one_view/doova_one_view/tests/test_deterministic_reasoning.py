# doova_one_view/tests/test_deterministic_reasoning.py

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "doova_one_view.settings")
django.setup()

import unittest
from unittest.mock import patch
from doova_one_view.api.agent.deterministic_reasoning import (
    _month_bounds,
    analyze_sales_change,
    analyze_revenue_gap,
    _get_sales_metrics
)

class TestDeterministicReasoning(unittest.TestCase):

    def test_month_bounds_calculation(self):
        """Verify _month_bounds returns exact start and end dates for various months including leap years."""
        start_jan, end_jan = _month_bounds(2026, 1)
        self.assertEqual(start_jan, "2026-01-01")
        self.assertEqual(end_jan, "2026-01-31")

        start_feb_leap, end_feb_leap = _month_bounds(2024, 2)
        self.assertEqual(start_feb_leap, "2024-02-01")
        self.assertEqual(end_feb_leap, "2024-02-29")

        start_feb_non_leap, end_feb_non_leap = _month_bounds(2025, 2)
        self.assertEqual(start_feb_non_leap, "2025-02-01")
        self.assertEqual(end_feb_non_leap, "2025-02-28")

    def test_analyze_sales_change_pattern_matching(self):
        """Verify analyze_sales_change extracts month-year pairs from message queries."""
        query_valid = "Compare sales performance between Jan 2025 and Feb 2026"
        res = analyze_sales_change(tenant_id="3fa85f64-5717-4562-b3fc-2c963f66afa6", message=query_valid)
        self.assertIsNotNone(res)
        self.assertIn("jan", str(res))
        self.assertIn("2025", str(res))
        self.assertIn("feb", str(res))
        self.assertIn("2026", str(res))

        query_invalid = "Show me sales for Jan 2025"  # Only 1 month mentioned
        res_invalid = analyze_sales_change(tenant_id="3fa85f64-5717-4562-b3fc-2c963f66afa6", message=query_invalid)
        self.assertIsNone(res_invalid)

    def test_analyze_revenue_gap_trigger(self):
        """Verify analyze_revenue_gap triggers when accounting, sales, and gap keywords are present."""
        gap_query = "Why is there a diff between accounting and sales revenue?"
        res = analyze_revenue_gap(tenant_id="default", message=gap_query)
        self.assertIsNotNone(res)
        self.assertIn("revenue gap", res.lower())

        normal_query = "Show me sales orders for accounting team"
        self.assertIsNone(analyze_revenue_gap(tenant_id="default", message=normal_query))

    @patch("doova_one_view.api.agent.deterministic_reasoning.run_query")
    def test_get_sales_metrics(self, mock_run_query):
        """Verify _get_sales_metrics builds correct parameters and calculates revenue totals."""
        mock_run_query.return_value = [{"revenue": 450000.0, "count": 15}]
        metrics = _get_sales_metrics(
            tenant_id="3fa85f64-5717-4562-b3fc-2c963f66afa6",
            company_ids=[1],
            start="2026-01-01",
            end="2026-01-31"
        )
        self.assertEqual(metrics["revenue"], 450000.0)
        self.assertEqual(metrics["count"], 15)

if __name__ == "__main__":
    unittest.main()
